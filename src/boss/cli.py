"""boss <command>. Run `boss --help`."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from string import Template

from boss import (
    backup,
    channels,
    desk,
    ladder,
    mail,
    meetings,
    progression,
    publish,
    review,
    tick,
    trackgen,
    tracks,
    wizard,
)
from boss.config import ENV_FILE, Config, ConfigError
from boss.llm import LLM, lane_options
from boss.persona import render, system_prompt
from boss.safety import strip_code
from boss.state import State, parse_iso

HANDBOOK = """\
# How $company_name works

$boss_name, $boss_title. Read it once.

## Tickets
One open ticket at a time. Each is its own folder under `tickets/` and its own git repo:
`TICKET.md` (brief, acceptance criteria, due date), `src/` (yours), `tests/` (mine),
`data/` (the client's). `uv sync` once, `uv run pytest -q` as often as you like.
Done means: tests green, ruff clean, every acceptance criterion holds, committed with a
message that says what changed. Hand in with `boss submit <id> -m "..."`. You get
APPROVED or CHANGES_REQUESTED, a score out of 5, and exactly what is wrong.
A ticket that comes back three times is a conversation.

## The rule
I do not write your code. Not a line, not "just this bit". I point, I ask, you type.
If I ever paste code at you, say so; that is a defect in me, not a gift to you.
$tutor_name explains concepts and quizzes you (`boss help "question"`), and does not write
your code either.

## Meetings
- Standup on standup days, async: `boss standup`, three lines. Yesterday, today, blockers.
  Facts, not feelings.
- 1:1 once a week: `boss meet <id>`. When you have the tickets for the next level, the
  1:1 is the gate. I ask, you answer, I decide. Vague answers do not pass.
- Client calls when a ticket needs scoping: `boss meet <id>`. You lead. Type /end to leave.
- `boss meetings` lists what is scheduled. Calendar files are under `calendar/`.

## Levels
$levels
`boss ladder` shows where you are.

## Sandbox rules
Everything stays under this folder. No production systems, no real client data, no real
credentials in code. Free-tier keys go in a gitignored `.env`; `.env.example` shows the shape.

## The desk
`boss desk` opens a local web page with the ticket, a thread with me, a thread with
$tutor_name, standups and notes. Reviews and 1:1s stay in the terminal.

## Out of character
Everything here is a simulation you set up yourself: the company, the clients and I are
fiction. Write /ooc in any conversation and the simulation answers plainly.

## Commands
`boss status`, `boss inbox`, `boss ticket <id>`, `boss submit <id> -m "..."`, `boss standup`,
`boss meet <id>`, `boss meetings`, `boss ladder`, `boss desk`, `boss tick`, `boss doctor`,
`boss help "question"` ($tutor_name), `boss ask "question"` (me).
"""


def handbook_text(cfg: Config) -> str:
    levels = "\n".join(f"- L{lv.number} {lv.name}" for lv in ladder.LEVELS)
    return Template(HANDBOOK).safe_substitute(
        company_name=cfg.company,
        boss_name=cfg.boss_name,
        boss_title=cfg.section("boss").get("title", "Head of Engineering"),
        tutor_name=desk.tutor_name(cfg),
        levels=levels,
    )


def _open(args: argparse.Namespace) -> tuple[Config, State, LLM | None]:
    cfg = Config.load(Path(args.config) if args.config else None)
    state = State(cfg.db_path)
    llm = None if getattr(args, "no_llm", False) else LLM(cfg, state)
    return cfg, state, llm


def cmd_init(args: argparse.Namespace) -> int:
    cfg, state, llm = _open(args)
    for d in (
        cfg.tickets_dir,
        cfg.inbox_dir,
        cfg.calendar_dir,
        cfg.meetings_dir,
        cfg.root / "reviews",
        cfg.root / "company",
    ):
        d.mkdir(parents=True, exist_ok=True)
    handbook = cfg.root / "company" / "HANDBOOK.md"
    if not handbook.exists():
        handbook.write_text(handbook_text(cfg), encoding="utf-8")
    if state.get_meta("level") is None:
        state.set_level(0, "init")
        channels.deliver(
            cfg,
            state,
            kind="welcome",
            subject=f"Welcome to {cfg.company}",
            body=(
                f"{cfg.engineer_name},\n\nWelcome aboard. Read company/HANDBOOK.md today; "
                f"the first ticket follows shortly. `boss meetings` shows the standups and "
                f"our weekly 1:1. Everything you need is under {cfg.root}.\n\n{cfg.boss_first}"
            ),
        )
        print(f"initialised {cfg.root}")
    else:
        print(f"already initialised at {cfg.root} (level L{state.level})")
    for line in tick.tick(cfg, state, llm, force=True):
        print(f"- {line}")
    print(f"\nNext: read {cfg.root}/INBOX.md, then `boss status`.")
    return 0


def cmd_tick(args: argparse.Namespace) -> int:
    cfg, state, llm = _open(args)
    for line in tick.tick(cfg, state, llm, force=args.force):
        print(f"- {line}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    cfg, state, _ = _open(args)
    level = state.level
    lvl = ladder.get_level(level)
    ok, why = progression.eligible(state, level)
    print(f"{cfg.company}: {cfg.engineer_name} reports to {cfg.boss_name}")
    print(f"Track: {tracks.active().name} ({cfg.track_name})")
    print(f"Level: L{level} {lvl.name} ({lvl.phase}); next level: {'ready' if ok else why}")
    open_rows = state.open_tickets()
    print(
        "Open tickets:" if open_rows else "Open tickets: none (next one arrives on the next tick)"
    )
    now = datetime.now(UTC)
    for t in open_rows:
        due = parse_iso(t["due_at"])
        flag = "OVERDUE" if now > due else f"due {due.astimezone(cfg.tz):%a %d %b %H:%M}"
        print(f"  {t['id']} {t['title']} [{t['client']}] {t['status']}, {flag}\n    {t['sandbox']}")
    upcoming = [
        m
        for m in state.meetings()
        if m["status"] in {"scheduled", "notified"} and parse_iso(m["when_at"]) > now
    ]
    print("Next meetings:" if upcoming else "Next meetings: none scheduled yet")
    for m in upcoming[:4]:
        print(
            f"  {m['id']} {meetings.LABEL.get(m['type'], m['type'])} "
            f"{parse_iso(m['when_at']).astimezone(cfg.tz):%a %d %b %H:%M}"
        )
    reviews = state.recent_reviews(1)
    if reviews:
        r = reviews[0]
        print(f"Last review: {r['ticket_id']} {r['verdict']} {r['score']}/5: {r['summary']}")
    print(
        f"LLM today: {state.quality_calls_today()} quality calls, "
        f"${state.spend_today():.2f} reported by the provider"
    )
    ch = cfg.section("channels")
    on = [k for k in ("inbox", "desktop", "ntfy", "email") if ch.get(k)]
    cap = int(ch.get("max_pushes_per_day", 2))
    print(
        f"Channels on: {', '.join(on)}. Pushes today: {state.pushes_today(cfg.tz)}/{cap} "
        f"(weekdays only). Inbox: {cfg.root}/INBOX.md"
    )
    return 0


def cmd_inbox(args: argparse.Namespace) -> int:
    cfg, state, _ = _open(args)
    rows = state.messages(args.n)
    for m in reversed(rows):
        print(f"\n=== {m['created_at']} [{m['kind']}] {m['subject']}\n{m['body']}")
    if not rows:
        print("inbox empty")
    return 0


def cmd_ticket(args: argparse.Namespace) -> int:
    cfg, state, _ = _open(args)
    t = state.get_ticket(args.id)
    if t is None:
        print(f"unknown ticket {args.id}", file=sys.stderr)
        return 1
    path = Path(t["sandbox"]) / "TICKET.md"
    print(path.read_text(encoding="utf-8") if path.exists() else t["brief"])
    print(f"\nStatus: {t['status']}   Sandbox: {t['sandbox']}")
    return 0


def cmd_submit(args: argparse.Namespace) -> int:
    cfg, state, llm = _open(args)
    print(f"Running the checks in the sandbox and sending the diff to {cfg.boss_first}...")
    try:
        result = review.submit(cfg, state, llm, args.id, args.message or "")
    except review.SubmitError as exc:
        print(f"cannot submit: {exc}", file=sys.stderr)
        return 1
    word = "approved" if result["verdict"] == "APPROVED" else "changes requested"
    subject = f"{args.id}: {word}, {result['score']}/5"
    body = result["body"]
    channels.deliver(cfg, state, kind="review", subject=subject, body=body, ticket_id=args.id)
    print("\n" + body)
    _publish_quietly(cfg, state)
    return 0


def cmd_standup(args: argparse.Namespace) -> int:
    cfg, state, llm = _open(args)
    if llm is None:
        print("standup needs the LLM", file=sys.stderr)
        return 1
    answers = None
    if args.yesterday or args.today or args.blockers:
        answers = {
            "yesterday": args.yesterday or "",
            "today": args.today or "",
            "blockers": args.blockers or "",
        }
    text = meetings.run_standup(cfg, state, llm, answers)
    channels.deliver(
        cfg, state, kind="standup", subject=f"Re: standup {datetime.now(cfg.tz):%A}", body=text
    )
    print(f"\n{cfg.boss_first}: {text}")
    _publish_quietly(cfg, state)
    return 0


def cmd_meet(args: argparse.Namespace) -> int:
    cfg, state, llm = _open(args)
    if llm is None:
        print("meetings need the LLM", file=sys.stderr)
        return 1
    try:
        outcome = meetings.run_meeting(cfg, state, llm, args.id)
    except (ValueError, RuntimeError) as exc:
        print(f"cannot hold meeting: {exc}", file=sys.stderr)
        return 1
    channels.deliver(
        cfg,
        state,
        kind="minutes",
        subject=f"Minutes {args.id}",
        body=outcome.get("minutes_md", ""),
        meeting_id=args.id,
    )
    print("\nMinutes:\n" + outcome.get("minutes_md", ""))
    if outcome.get("level_up"):
        print(outcome["level_up"])
    _publish_quietly(cfg, state)
    return 0


def cmd_meetings(args: argparse.Namespace) -> int:
    cfg, state, _ = _open(args)
    for m in state.meetings():
        when = parse_iso(m["when_at"]).astimezone(cfg.tz)
        print(f"{m['id']} {m['type']:12} {when:%a %d %b %H:%M} {m['status']:9} {m['client'] or ''}")
    return 0


def cmd_ladder(args: argparse.Namespace) -> int:
    cfg, state, _ = _open(args)
    current = state.level
    for lvl in ladder.LEVELS:
        mark = ">" if lvl.number == current else " "
        n = state.accepted_count(lvl.number)
        print(
            f"{mark} L{lvl.number} {lvl.name} ({lvl.phase}): {n}/{lvl.required_accepted} accepted"
        )
    lvl = ladder.get_level(current)
    print("\nThis level trains:")
    for c in lvl.competencies:
        print(f"  - {c}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    cfg, state, llm = _open(args)
    ok = True
    print(f"ok  settings: {cfg.toml_path}")
    print(f"ok  track: {tracks.active().name} ({len(ladder.LEVELS)} levels)")
    for tool in ("git", "uv"):
        found = shutil.which(tool)
        print(f"{'ok ' if found else 'MISSING'} {tool}: {found or 'not on PATH'}")
        ok &= bool(found)
    s = cfg.secrets
    for lane in ("quality", "cheap"):
        opts = lane_options(cfg, lane)
        provider = opts["provider"]
        if provider == "none":
            print(f"--  llm.{lane}: off")
            continue
        detail = f"{provider}, model {opts.get('model') or '(not set)'}"
        good = bool(opts.get("model"))
        if provider == "claude-cli":
            found = shutil.which(str(opts.get("bin", "claude")))
            good &= bool(found)
            detail += f", {found or 'claude CLI not on PATH'}"
        else:
            detail += f", {opts.get('base_url') or '(no base_url)'}"
            good &= bool(opts.get("base_url"))
            key_name = opts.get("api_key_env")
            if key_name:
                good &= bool(s.get(key_name))
                detail += f", {key_name} {'set' if s.get(key_name) else f'MISSING in {ENV_FILE}'}"
        print(f"{'ok ' if good else 'FAIL'} llm.{lane}: {detail}")
        ok &= good
    if not llm or not llm.available():
        print("--  no model configured: built-in starter tickets and fact-only reviews")
    primary, second = mail.profile(s, ""), mail.profile(s, "2")
    where = primary["HOST"] + " -> " + primary["TO"] if primary else f"not configured ({ENV_FILE})"
    print(f"{'ok ' if primary else '-- '} mail primary (SMTP_*): {where}")
    if second:
        print(f"ok  mail backup (SMTP2_*): {second['HOST']} as {second['USER']}")
    ch = cfg.section("channels")
    print(
        f"--  channels: inbox on, desktop {ch.get('desktop')}, ntfy {ch.get('ntfy')} "
        f"({ch.get('ntfy_topic') or 'no topic'}), email {ch.get('email')}"
    )
    print(f"ok  root: {cfg.root} ({'exists' if cfg.root.exists() else 'will be created by init'})")
    if args.llm and llm is not None:
        for lane in ("quality", "cheap"):
            if lane_options(cfg, lane)["provider"] == "none":
                continue
            call = llm.quality if lane == "quality" else llm.cheap
            reply = call("Reply with the single word OK.", "Ping.", purpose="doctor")
            print(
                f"{'ok ' if reply.ok else 'FAIL'} {lane} lane answered: "
                f"{reply.text.strip()[:40] if reply.ok else reply.error} ({reply.seconds:.1f}s)"
            )
            ok &= reply.ok
    return 0 if ok else 1


def cmd_test_channels(args: argparse.Namespace) -> int:
    cfg, state, _ = _open(args)
    results = channels.deliver(
        cfg,
        state,
        kind="test",
        subject="Testing the mail setup",
        body=(
            f"{cfg.engineer_name},\n\nTesting the mail setup. If this reached you, it works. "
            f"No reply needed.\n\n{cfg.boss_first}"
        ),
        force=True,
    )
    for k, v in results.items():
        print(f"{k}: {v}")
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    cfg, state, _ = _open(args)
    print(desk.sync(cfg, state))
    _publish_quietly(cfg, state)
    return 0


def _local_event(cfg: Config, event: dict) -> None:
    desk.append_event(cfg.root / "desk" / "local", event)


def cmd_help(args: argparse.Namespace) -> int:
    """Ask the tutor (study mode) with the open ticket attached. Explains; never codes."""
    cfg, state, llm = _open(args)
    name = desk.tutor_name(cfg)
    question = " ".join(args.question).strip()
    if not question:
        print('boss help "your question"', file=sys.stderr)
        return 1
    if llm is None or not llm.available():
        print(f"{name} needs a model; see `boss doctor`.", file=sys.stderr)
        return 1
    rows = state.open_tickets()
    ticket = desk._ticket_dict(cfg, dict(rows[0]), datetime.now(UTC)) if rows else None
    print(f"Asking {name} (study mode: explains and quizzes, never writes your code)...")
    earlier = desk.thread_context(cfg, state, ticket["id"] if ticket else None)
    r = llm.ask(
        desk.tutor_system(cfg),
        desk.tutor_prompt(cfg, state, ticket, question, earlier),
        purpose="help (tutor)",
    )
    ok = r.ok and bool(r.text.strip())
    reply = strip_code(r.text.strip()) if ok else desk.OFFLINE_TUTOR
    print(f"\n{name}: {reply}")
    if not ok:
        print(f"[{r.lane} lane: {r.error}]", file=sys.stderr)
    _local_event(
        cfg,
        {
            "kind": "tutor_chat",
            "ticket": ticket["id"] if ticket else "general",
            "question": question,
            "reply": reply,
            "ok": ok,
            "model": r.model,
        },
    )
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    """A quick question to the boss from the terminal, ticket attached."""
    cfg, state, llm = _open(args)
    if llm is None:
        print("ask needs the LLM", file=sys.stderr)
        return 1
    question = " ".join(args.question).strip()
    if not question:
        print('boss ask "your question"', file=sys.stderr)
        return 1
    rows = state.open_tickets()
    t = desk._ticket_dict(cfg, dict(rows[0]), datetime.now(UTC)) if rows else None
    earlier = desk.thread_context(cfg, state, t["id"] if t else None)
    prompt = render(
        "desk",
        tutor_name=desk.tutor_name(cfg),
        engineer_name=cfg.engineer_name,
        boss_name=cfg.boss_name,
        ticket_id=t["id"] if t else "none",
        title=t["title"] if t else "no open ticket",
        client=t["client"] if t else "",
        status=t["status"] if t else "",
        due=t["due_local"] if t else "",
        brief=(t["brief"][:1500] if t else "(no ticket)"),
        acceptance="\n".join(f"- {a}" for a in (t["acceptance"] if t else [])) or "- (none)",
        history=("Earlier:\n" + earlier) if earlier else "",
        question=question,
    )
    reply = llm.ask(
        system_prompt(cfg, state), prompt, purpose="terminal question", prefer="quality"
    )
    text = strip_code(reply.text.strip()) if reply.ok else desk.OFFLINE_BOSS
    print(f"\n{cfg.boss_first}: {text}")
    if not reply.ok:
        print(f"[{reply.lane} lane: {reply.error}]", file=sys.stderr)
    _local_event(
        cfg,
        {
            "kind": "boss_chat",
            "ticket": t["id"] if t else "general",
            "question": question,
            "reply": text,
            "ok": reply.ok,
            "model": reply.model,
        },
    )
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    cfg, state, _ = _open(args)
    print(backup.run(cfg, state))
    return 0


def cmd_answer(args: argparse.Namespace) -> int:
    """Pull the desk, answer what waits there now, publish. What the tick does every run."""
    cfg, state, llm = _open(args)
    if llm is None:
        print("answer needs the LLM", file=sys.stderr)
        return 1
    print(desk.sync(cfg, state))
    n = desk.answer_pending(cfg, state, llm, limit=args.limit)
    print(f"answered {n} desk item(s); {len(state.pending_desk_questions(50))} still waiting")
    _publish_quietly(cfg, state)
    return 0


def cmd_notebook(args: argparse.Namespace) -> int:
    """The boss's private notes about you. Your sandbox, your call to read them."""
    cfg, state, _ = _open(args)
    if args.add:
        state.add_note("admin", args.add)
        print("noted")
    rows = state.notes(args.n)
    if not rows:
        print(f"{cfg.boss_first} has not written anything about you yet.")
    for r in rows:
        print(f"{r['at'][:16]} [{r['source']}] {r['text']}")
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    from boss import evals

    cfg, state, llm = _open(args)
    if args.replay:
        results = evals.replay(cfg, state, llm, use_judge=args.judge, limit=args.limit or 30)
        title = "replay"
    else:
        if llm is None:
            print("eval needs the LLM (or use --replay)", file=sys.stderr)
            return 1
        results = evals.run(
            cfg,
            state,
            llm,
            only=args.prompt,
            lane=args.lane,
            use_judge=args.judge,
            limit=args.limit,
        )
        title = f"{args.prompt or 'all'}-{args.lane}"
    path = evals.report(cfg, results, title)
    passed = sum(1 for r in results if r.ok)
    for r in results:
        mark = "PASS" if r.ok else ("SKIP" if r.skipped else "FAIL")
        detail = r.skipped or ", ".join(r.failures)
        if r.judge and r.judge.get("fail"):
            detail += f" | judge: {r.judge.get('reason', '')}"
        print(f"{mark:4} {r.case_id:34} {detail}")
    print(f"\n{passed}/{len(results)} passed. Report: {path}")
    return 0 if passed == len(results) else 1


def cmd_desk(args: argparse.Namespace) -> int:
    cfg, state, _ = _open(args)
    desk.serve(cfg, state, local=True)
    return 0


def cmd_desk_serve(args: argparse.Namespace) -> int:
    cfg, state, _ = _open(args)
    desk.serve(cfg, state, local=False)
    return 0


def cmd_desk_deploy(args: argparse.Namespace) -> int:
    cfg, _, _ = _open(args)
    for line in desk.deploy(cfg):
        print(f"- {line}")
    return 0


def _publish_quietly(cfg: Config, state: State) -> None:
    if cfg.section("web").get("enabled"):
        try:
            print(publish.publish(cfg, state, timeout=45), file=sys.stderr)
        except Exception as exc:  # noqa: BLE001 - publishing must never break a command
            print(f"publish skipped: {type(exc).__name__}", file=sys.stderr)


def cmd_publish(args: argparse.Namespace) -> int:
    cfg, state, _ = _open(args)
    print(publish.publish(cfg, state))
    return 0


def cmd_install_timer(args: argparse.Namespace) -> int:
    """Linux with systemd. Elsewhere, run `boss tick` from cron or Task Scheduler."""
    cfg, _, _ = _open(args)
    if not shutil.which("systemctl"):
        print(
            "systemctl not found. Schedule this line every 15 minutes instead:\n"
            f"  {sys.executable} -m boss --config {cfg.toml_path} tick",
            file=sys.stderr,
        )
        return 1
    unit_dir = Path("~/.config/systemd/user").expanduser()
    unit_dir.mkdir(parents=True, exist_ok=True)
    path_env = f"{Path.home()}/.local/bin:/usr/local/bin:/usr/bin:/bin"
    src_dir = Path(__file__).resolve().parents[1]
    service = (
        "[Unit]\nDescription=fenrir-boss tick (tickets, meetings, nudges)\n"
        "After=network-online.target\n\n"
        "[Service]\nType=oneshot\n"
        f"Environment=PATH={path_env}\nEnvironment=HOME={Path.home()}\n"
        f"Environment=PYTHONPATH={src_dir}\n"
        f"ExecStart={sys.executable} -m boss --config {cfg.toml_path} tick\n"
    )
    timer = (
        "[Unit]\nDescription=fenrir-boss tick every 15 minutes\n\n[Timer]\n"
        "OnCalendar=*:0/15\nRandomizedDelaySec=90\nPersistent=true\n\n"
        "[Install]\nWantedBy=timers.target\n"
    )
    (unit_dir / "fenrir-boss.service").write_text(service, encoding="utf-8")
    (unit_dir / "fenrir-boss.timer").write_text(timer, encoding="utf-8")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    subprocess.run(["systemctl", "--user", "enable", "--now", "fenrir-boss.timer"], check=False)
    print("installed fenrir-boss.timer (every 15 min). Check: systemctl --user list-timers")
    return 0


def cmd_track(args: argparse.Namespace) -> int:
    cfg, state, llm = _open(args)
    if args.action == "list":
        for key, path in tracks.available(cfg.root).items():
            t = tracks.load_file(path)
            mark = ">" if key == cfg.track_name else " "
            print(f"{mark} {key}: {t.name}, {len(t.levels)} levels. {t.summary}")
        print("\nSwitch by editing [sim] track in", cfg.toml_path)
        return 0
    if args.action == "show":
        t = tracks.load_file(tracks.find(args.name or cfg.track_name, cfg.root))
        print(f"{t.name} ({t.key}): {t.summary}\nRole: {t.role}\nFile: {t.source}\n")
        for lv in t.levels:
            print(f"L{lv.number} {lv.name} [{lv.kind}], {lv.required_accepted} tickets to pass")
            for c in lv.competencies:
                print(f"    - {c}")
        print("\nClients: " + ", ".join(c["name"] for c in t.clients))
        for sr in t.series:
            print(f"Series: {sr.name} (L{sr.levels[0]} to L{sr.levels[1]})")
        return 0
    if args.action == "check":
        t = tracks.load_file(tracks.find(args.name or cfg.track_name, cfg.root))
        print(f"ok: {t.key}, {len(t.levels)} levels, {len(t.clients)} clients")
        return 0
    if llm is None or not llm.available():
        print("track new needs a model; see `boss doctor`.", file=sys.stderr)
        return 1
    if not args.role:
        print('boss track new --role "data analyst at a hospital"', file=sys.stderr)
        return 1
    print("Drafting a track (one or two long model calls, a few minutes)...")
    try:
        path = trackgen.new_track(cfg, llm, args.role, notes=args.notes or "", key=args.name or "")
    except trackgen.GenerationError as exc:
        print(f"no track: {exc}", file=sys.stderr)
        return 1
    print(f'wrote {path}\nRead it, edit it, then set [sim] track = "{path.stem}" in')
    print(f"{cfg.toml_path}. A track change mid-way keeps your level number; use")
    print("`boss admin-level 0` to start the new ladder from the bottom.")
    return 0


def cmd_persona(args: argparse.Namespace) -> int:
    cfg, state, llm = _open(args)
    if args.action == "show":
        print(system_prompt(cfg, state))
        return 0
    if llm is None or not llm.available():
        print("persona generate needs a model; see `boss doctor`.", file=sys.stderr)
        return 1
    try:
        path = trackgen.new_bible(cfg, llm, notes=args.notes or "")
    except trackgen.GenerationError as exc:
        print(f"no backstory: {exc}", file=sys.stderr)
        return 1
    print(f'wrote {path}\nTo use it, set in {cfg.toml_path}:\n  [boss]\n  bible = "{path}"')
    return 0


def cmd_admin_level(args: argparse.Namespace) -> int:
    cfg, state, _ = _open(args)
    state.set_level(args.level, f"admin override: {args.reason}")
    print(f"level set to L{args.level}. {cfg.boss_first} will notice; expect the gate questions.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="boss",
        description="A simulated workplace that trains you: tickets, sandboxes, reviews, "
        "meetings. Start with `boss setup`.",
    )
    p.add_argument(
        "--config", help="path to boss.toml (default: ./boss.toml, then ~/.config/fenrir-boss/)"
    )
    p.add_argument(
        "--no-llm", action="store_true", help="never call a model (seeds and checks only)"
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("setup", help="name the company, the boss and yourself; write boss.toml")
    st.add_argument("--yes", action="store_true", help="accept every default, ask nothing")
    st.add_argument("--force", action="store_true", help="overwrite an existing boss.toml")
    st.add_argument("--setting", choices=list(wizard.SETTINGS))
    st.add_argument("--company")
    st.add_argument("--city")
    st.add_argument("--boss", help="the boss's (or instructor's) full name")
    st.add_argument("--title")
    st.add_argument("--intensity", choices=list(wizard.INTENSITIES))
    st.add_argument("--tutor", help="name of the study-mode tutor")
    st.add_argument("--name", help="your first name")
    st.add_argument("--pronouns")
    st.add_argument("--timezone")
    st.add_argument("--hours", help="hours a week")
    st.add_argument("--root", help="folder for sandboxes and state")
    st.add_argument("--track")
    st.add_argument("--role", help="the role you are training for")
    st.add_argument("--provider", choices=list(wizard.PROVIDERS))
    st.add_argument("--base-url", dest="base_url")
    st.add_argument("--quality-model", dest="quality_model")
    st.add_argument("--cheap-model", dest="cheap_model")
    st.set_defaults(fn=wizard.run)
    tr = sub.add_parser("track", help="list, show, check, or draft a new track for any role")
    tr.add_argument("action", choices=["list", "show", "check", "new"])
    tr.add_argument("name", nargs="?", help="track key (for new: the key to save under)")
    tr.add_argument("--role", help='for new: e.g. "data analyst at a hospital"')
    tr.add_argument("--notes", help="for new: where you start, what you want to be able to do")
    tr.set_defaults(fn=cmd_track)
    pe = sub.add_parser("persona", help="show the boss's full prompt, or generate a backstory")
    pe.add_argument("action", choices=["show", "generate"])
    pe.add_argument("--notes", help="for generate: wishes for the character")
    pe.set_defaults(fn=cmd_persona)
    sub.add_parser(
        "init", help="create the sandbox root, the handbook and the first ticket"
    ).set_defaults(fn=cmd_init)
    t = sub.add_parser("tick", help="run the scheduler once (the timer calls this)")
    t.add_argument("--force", action="store_true", help="ignore quiet hours and the ticket gap")
    t.set_defaults(fn=cmd_tick)
    sub.add_parser("status", help="level, open ticket, next meetings, spend").set_defaults(
        fn=cmd_status
    )
    i = sub.add_parser("inbox", help="print the latest messages")
    i.add_argument("-n", type=int, default=5)
    i.set_defaults(fn=cmd_inbox)
    tk = sub.add_parser("ticket", help="print a ticket brief")
    tk.add_argument("id")
    tk.set_defaults(fn=cmd_ticket)
    s = sub.add_parser("submit", help="hand a ticket in for review")
    s.add_argument("id")
    s.add_argument("-m", "--message", default="", help="what you did and what you are unsure about")
    s.set_defaults(fn=cmd_submit)
    su = sub.add_parser("standup", help="answer the standup (interactive, or with flags)")
    su.add_argument("--yesterday")
    su.add_argument("--today")
    su.add_argument("--blockers")
    su.set_defaults(fn=cmd_standup)
    me = sub.add_parser("meet", help="hold a 1:1 or a client call in the terminal")
    me.add_argument("id")
    me.set_defaults(fn=cmd_meet)
    sub.add_parser("meetings", help="list meetings").set_defaults(fn=cmd_meetings)
    sub.add_parser("ladder", help="show the level ladder and where you are").set_defaults(
        fn=cmd_ladder
    )
    d = sub.add_parser("doctor", help="check tools, keys and channels")
    d.add_argument("--llm", action="store_true", help="also ping both model lanes")
    d.set_defaults(fn=cmd_doctor)
    sub.add_parser(
        "test-channels", help="send a test message through every enabled channel"
    ).set_defaults(fn=cmd_test_channels)
    sub.add_parser("publish", help="render the site; upload it when [web] is on").set_defaults(
        fn=cmd_publish
    )
    sub.add_parser(
        "sync", help="pull what happened on the web desk into the state database"
    ).set_defaults(fn=cmd_sync)
    h = sub.add_parser("help", help="ask the tutor (study mode) with the open ticket attached")
    h.add_argument("question", nargs="*")
    h.set_defaults(fn=cmd_help)
    q = sub.add_parser("ask", help="a quick question to the boss, ticket attached")
    q.add_argument("question", nargs="*")
    q.set_defaults(fn=cmd_ask)
    sub.add_parser(
        "backup", help="copy the state and the text record to the backup dir"
    ).set_defaults(fn=cmd_backup)
    an = sub.add_parser("answer", help="answer what waits on the desk now, then publish")
    an.add_argument("--limit", type=int, default=4)
    an.set_defaults(fn=cmd_answer)
    nb = sub.add_parser("notebook", help="the boss's private notes about you (or --add one)")
    nb.add_argument("-n", type=int, default=20)
    nb.add_argument("--add", help="add a line to the notebook, e.g. a fact to remember")
    nb.set_defaults(fn=cmd_notebook)
    ev = sub.add_parser("eval", help="run the prompt evals, or --replay the checks on past output")
    ev.add_argument("--prompt", choices=["desk", "standup", "nudge", "desk_note", "review"])
    ev.add_argument("--lane", choices=["cheap", "quality"], default="cheap")
    ev.add_argument(
        "--judge", action="store_true", help="one quality-lane call per output as judge"
    )
    ev.add_argument("--replay", action="store_true", help="check what was already sent, no model")
    ev.add_argument("--limit", type=int)
    ev.set_defaults(fn=cmd_eval)
    sub.add_parser(
        "desk", help="open the local web desk on http://127.0.0.1:8110/desk/"
    ).set_defaults(fn=cmd_desk)
    sub.add_parser("desk-serve", help="self-hosting: API only, behind your proxy").set_defaults(
        fn=cmd_desk_serve
    )
    sub.add_parser(
        "desk-deploy", help="self-hosting: copy the package to your server and restart the desk"
    ).set_defaults(fn=cmd_desk_deploy)
    sub.add_parser("install-timer", help="install the systemd user timer (Linux)").set_defaults(
        fn=cmd_install_timer
    )
    a = sub.add_parser("admin-level", help="override the level (your sandbox, your call)")
    a.add_argument("level", type=int)
    a.add_argument("--reason", default="manual")
    a.set_defaults(fn=cmd_admin_level)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.fn(args))
    except (ConfigError, tracks.TrackError) as exc:
        print(f"boss: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    except json.JSONDecodeError as exc:
        print(f"state error: {exc}", file=sys.stderr)
        return 2
