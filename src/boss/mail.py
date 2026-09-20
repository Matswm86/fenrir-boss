"""Plain SMTP with two optional profiles: SMTP_* (primary) and SMTP2_* (backup)."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

PROFILE_KEYS = ("HOST", "PORT", "USER", "PASSWORD", "FROM", "TO")


def profile(secrets: dict[str, str], prefix: str) -> dict[str, str] | None:
    """SMTP_* (prefix '') or SMTP2_* (prefix '2'). None unless the five needed keys exist."""
    p = {k: secrets.get(f"SMTP{prefix}_{k}", "") for k in PROFILE_KEYS}
    if prefix and not p["TO"]:
        p["TO"] = secrets.get("SMTP_TO", "")
    if not all(p[k] for k in ("HOST", "USER", "PASSWORD", "FROM", "TO")):
        return None
    p["PORT"] = p["PORT"] or "465"
    return p


def send(
    prof: dict[str, str],
    display_name: str,
    subject: str,
    body: str,
    ics: tuple[str, str] | None = None,
) -> str:
    msg = EmailMessage()
    msg["From"] = f"{display_name} <{prof['FROM']}>"
    msg["To"] = prof["TO"]
    msg["Subject"] = subject
    msg.set_content(body)
    if ics:
        name, text = ics
        msg.add_attachment(
            text.encode("utf-8"),
            maintype="text",
            subtype="calendar",
            filename=name,
            params={"method": "REQUEST"},
        )
    port = int(prof["PORT"])
    try:
        if port == 465:
            with smtplib.SMTP_SSL(prof["HOST"], port, timeout=25) as srv:
                srv.login(prof["USER"], prof["PASSWORD"])
                srv.send_message(msg)
        else:
            with smtplib.SMTP(prof["HOST"], port, timeout=25) as srv:
                srv.starttls()
                srv.login(prof["USER"], prof["PASSWORD"])
                srv.send_message(msg)
        return "ok"
    except (smtplib.SMTPException, OSError) as exc:
        return f"{type(exc).__name__}: {str(exc)[:160]}"
