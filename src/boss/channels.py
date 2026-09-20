"""Deliver a message from the boss through every enabled channel. The inbox file is always on."""

from __future__ import annotations

import shutil
import subprocess
import urllib.error
import urllib.request
from datetime import datetime

from boss import mail
from boss.config import Config
from boss.state import State

# Only these leave the inbox. Invites, reminders, agendas, standup replies, minutes and
# welcome notes stay in the inbox and on the desk: a manager does not mail you about a
# meeting you can see in your calendar.
PUSH_KINDS = frozenset({"ticket", "review", "nudge", "note", "test"})


def _now_local(cfg: Config) -> datetime:
    return datetime.now(cfg.tz)


def hold_reason(cfg: Config, state: State, kind: str) -> str:
    """Why a message stays in the inbox instead of being pushed; empty when it may go out."""
    ch = cfg.section("channels")
    if kind not in PUSH_KINDS:
        return f"{kind} stays in the inbox"
    days = [int(d) for d in ch.get("push_days", [0, 1, 2, 3, 4])]
    if _now_local(cfg).weekday() not in days:
        return "weekend"
    cap = int(ch.get("max_pushes_per_day", 2))
    if state.pushes_today(cfg.tz) >= cap:
        return f"daily cap of {cap} pushes reached"
    return ""


def deliver(
    cfg: Config,
    state: State,
    *,
    kind: str,
    subject: str,
    body: str,
    ticket_id: str | None = None,
    meeting_id: str | None = None,
    ics: tuple[str, str] | None = None,
    quiet: bool = False,
    force: bool = False,
) -> dict:
    """Inbox always. quiet=True records the message and stops there (desk events he already
    read). Otherwise a push (desktop, email, phone) goes out only for PUSH_KINDS, on push_days,
    under max_pushes_per_day; force=True skips those checks (explicit channel tests). Email
    when configured, ntfy gets the message itself once, desktop if notify-send exists."""
    message_id = state.add_message(
        kind=kind, subject=subject, body=body, ticket_id=ticket_id, meeting_id=meeting_id
    )
    ch = cfg.section("channels")
    results = {"inbox": _inbox(cfg, message_id, kind, subject, body)}
    if quiet:
        state.set_delivery(message_id, results)
        return results
    held = "" if force else hold_reason(cfg, state, kind)
    if held:
        results["push"] = f"held: {held}"
        state.set_delivery(message_id, results)
        return results
    if ch.get("desktop", True):
        results["desktop"] = _desktop(cfg, subject, body)
    if ch.get("email"):
        results["email"] = _email(cfg, subject, body, ics)
    if ch.get("ntfy"):
        # The message itself, once. No second "mail sent" ping on top of the mail.
        results["ntfy"] = _ntfy(cfg, subject, body)
    state.set_delivery(message_id, results)
    return results


def _inbox(cfg: Config, message_id: int, kind: str, subject: str, body: str) -> str:
    cfg.inbox_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(cfg.tz)
    path = cfg.inbox_dir / f"{stamp:%Y-%m-%d-%H%M}-{kind}-{message_id:04d}.md"
    text = (
        f"From: {cfg.boss_name}, {cfg.company}\n"
        f"Date: {stamp:%A %d %B %Y, %H:%M}\n"
        f"Subject: {subject}\n\n{body.strip()}\n"
    )
    path.write_text(text, encoding="utf-8")
    with (cfg.root / "INBOX.md").open("a", encoding="utf-8") as fh:
        fh.write(f"- {stamp:%Y-%m-%d %H:%M} [{kind}] {subject} -> inbox/{path.name}\n")
    return str(path)


def _desktop(cfg: Config, subject: str, body: str) -> str:
    if not shutil.which("notify-send"):
        return "skipped: notify-send not installed"
    try:
        subprocess.run(
            ["notify-send", f"{cfg.boss_first}: {subject}", body[:200]], timeout=5, check=False
        )
        return "ok"
    except (subprocess.TimeoutExpired, OSError) as exc:
        return f"error: {type(exc).__name__}"


def _ntfy(cfg: Config, subject: str, body: str, priority: int = 3, tags: str = "briefcase") -> str:
    ch = cfg.section("channels")
    topic = ch.get("ntfy_topic") or cfg.secrets.get("NTFY_TOPIC", "")
    if not topic:
        return "skipped: no topic"
    url = f"{ch.get('ntfy_server', 'https://ntfy.sh').rstrip('/')}/{topic}"
    req = urllib.request.Request(
        url,
        data=body[:800].encode("utf-8"),
        headers={
            "Title": f"{cfg.boss_first}: {subject}".encode().decode("latin-1", "replace"),
            "Priority": str(priority),
            "User-Agent": "fenrir-boss",
            "Tags": tags,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return "ok" if resp.status // 100 == 2 else f"http {resp.status}"
    except (urllib.error.URLError, TimeoutError) as exc:
        return f"error: {type(exc).__name__}"


def _email(cfg: Config, subject: str, body: str, ics: tuple[str, str] | None) -> str:
    """Primary SMTP profile first (SMTP_*), then the optional backup profile (SMTP2_*)."""
    secrets = cfg.secrets
    errors: list[str] = []
    for label, prefix in (("primary", ""), ("backup", "2")):
        prof = mail.profile(secrets, prefix)
        if prof is None:
            continue
        result = mail.send(prof, cfg.boss_name, subject, body, ics)
        if result == "ok":
            return f"ok via {label} to {prof['TO']}"
        errors.append(f"{label}: {result}")
    if not errors:
        return "skipped: no SMTP_* profile in the private env file"
    return "failed: " + "; ".join(errors)
