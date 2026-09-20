"""Standups, 1:1s and client calls: scheduling, calendar files, and holding them in the terminal."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta

from boss import clients, ladder, progression
from boss.config import Config
from boss.llm import LLM, extract_json
from boss.persona import render, system_prompt
from boss.state import State, parse_iso

DURATION_MIN = {"standup": 15, "one_on_one": 30, "client_call": 30}
LABEL = {"standup": "Standup", "one_on_one": "1:1", "client_call": "Client call"}


def _parse_hhmm(value: str) -> time:
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


def ics_text(
    cfg: Config, meeting_id: str, mtype: str, when: datetime, agenda: str, client: str | None
) -> str:
    start = when.astimezone(UTC)
    end = start + timedelta(minutes=DURATION_MIN.get(mtype, 30))
    title = LABEL.get(mtype, mtype)
    if client:
        title += f": {client}"
    desc = agenda.replace("\n", "\\n")
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//fenrir-boss//EN\r\nMETHOD:REQUEST\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{meeting_id}@fenrir-boss.invalid\r\n"
        f"DTSTAMP:{datetime.now(UTC):%Y%m%dT%H%M%SZ}\r\n"
        f"DTSTART:{start:%Y%m%dT%H%M%SZ}\r\nDTEND:{end:%Y%m%dT%H%M%SZ}\r\n"
        f"SUMMARY:{title}\r\nDESCRIPTION:{desc}\r\n"
        f"ORGANIZER;CN={cfg.boss_name}:mailto:boss@fenrir-boss.invalid\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )


def schedule(
    cfg: Config,
    state: State,
    *,
    mtype: str,
    when: datetime,
    agenda: str,
    ticket_id: str | None = None,
    client: str | None = None,
) -> dict | None:
    when_iso = when.astimezone(UTC).isoformat(timespec="seconds")
    if state.meeting_exists(mtype, when_iso):
        return None
    seq = state.next_seq("meeting")
    meeting_id = f"{cfg.meeting_prefix}-{seq:04d}"
    row = {
        "id": meeting_id,
        "seq": seq,
        "type": mtype,
        "when_at": when_iso,
        "status": "scheduled",
        "agenda": agenda,
        "ticket_id": ticket_id,
        "client": client,
    }
    state.insert_meeting(row)
    cfg.calendar_dir.mkdir(parents=True, exist_ok=True)
    (cfg.calendar_dir / f"{meeting_id}.ics").write_text(
        ics_text(cfg, meeting_id, mtype, when, agenda, client), encoding="utf-8"
    )
    return row


def plan_week(cfg, state, now: datetime) -> list[dict]:
    """Create the standing standups and the weekly 1:1 for the next seven days. Idempotent."""
    sched = cfg.section("schedule")
    local_now = now.astimezone(cfg.tz)
    created: list[dict] = []
    standup_t = _parse_hhmm(sched.get("standup_time", "09:00"))
    one_t = _parse_hhmm(sched.get("one_on_one_time", "14:00"))
    for offset in range(0, 7):
        day = (local_now + timedelta(days=offset)).date()
        if day.weekday() in sched.get("standup_days", [0, 2, 4]):
            when = datetime.combine(day, standup_t, tzinfo=cfg.tz)
            if when > local_now:
                row = schedule(
                    cfg,
                    state,
                    mtype="standup",
                    when=when,
                    agenda="Async standup. Run `boss standup` and answer three questions: "
                    "yesterday, today, blockers. Two minutes.",
                )
                if row:
                    created.append(row)
        if day.weekday() == int(sched.get("one_on_one_day", 4)):
            when = datetime.combine(day, one_t, tzinfo=cfg.tz)
            if when > local_now:
                level = state.level
                agenda = (
                    "Weekly 1:1. Progress this week, the open ticket, blockers, what you "
                    "want more of and less of."
                )
                if progression.needs_gate_meeting(state, level):
                    agenda += (
                        f" Gate probe: you have enough accepted tickets at L{level}; I ask the "
                        "gate questions and decide whether you move up."
                    )
                row = schedule(cfg, state, mtype="one_on_one", when=when, agenda=agenda)
                if row:
                    created.append(row)
    return created


def schedule_from_spec(cfg, state, ticket: dict, now: datetime) -> dict | None:
    spec = ticket.get("spec") or json.loads(ticket["spec_json"])
    meeting = spec.get("meeting")
    if not meeting:
        return None
    local = now.astimezone(cfg.tz) + timedelta(days=int(meeting.get("in_days", 1)))
    when = datetime.combine(local.date(), time(10, 0), tzinfo=cfg.tz)
    return schedule(
        cfg,
        state,
        mtype=meeting["type"],
        when=when,
        agenda=meeting.get("agenda", ""),
        ticket_id=ticket["id"],
        client=ticket["client"],
    )


def due(cfg, state, now: datetime) -> list[tuple[dict, str]]:
    """(meeting, 'reminder'|'agenda') pairs that need a message now. Uses once-keys."""
    out: list[tuple[dict, str]] = []
    for m in state.meetings():
        if m["status"] not in {"scheduled", "notified"}:
            continue
        when = parse_iso(m["when_at"])
        delta = when - now
        if timedelta(hours=-1) <= delta <= timedelta(minutes=60) and state.once(
            f"agenda:{m['id']}"
        ):
            out.append((dict(m), "agenda"))
        elif timedelta(hours=12) < delta <= timedelta(hours=26) and state.once(
            f"reminder:{m['id']}"
        ):
            out.append((dict(m), "reminder"))
        elif delta < timedelta(hours=-3):
            state.update_meeting(m["id"], status="missed")
    return out


# --- holding meetings ----------------------------------------------------------------


def _open_ticket_line(state: State, with_brief: bool = False) -> str:
    rows = state.open_tickets()
    if not rows:
        return "none"
    t = rows[0]
    due_local = parse_iso(t["due_at"]).astimezone().strftime("%a %d %b %H:%M")
    line = f"{t['id']} {t['title']} ({t['client']}), status {t['status']}, due {due_local}"
    if with_brief:
        line += "\nThe brief, so you only refer to what the ticket says:\n" + t["brief"][:1200]
    return line


def _desk_context(cfg: Config, state: State) -> str:
    """What he asked on the web desk about the open ticket, so she does not repeat herself."""
    from boss import desk

    rows = state.open_tickets()
    text = desk.thread_context(cfg, state, rows[0]["id"] if rows else None)
    return ("\nWhat he asked on the desk lately:\n" + text) if text else ""


def record_standup(
    cfg: Config, state: State, answers: dict[str, str], text: str, when: datetime | None = None
) -> str:
    """Store a standup (answers plus the boss's reply) against that day's meeting, or as ad hoc."""
    when = when or datetime.now(UTC)
    day = when.astimezone(cfg.tz).date()
    meeting = next(
        (
            m
            for m in state.meetings()
            if m["type"] == "standup" and parse_iso(m["when_at"]).astimezone(cfg.tz).date() == day
        ),
        None,
    )
    transcript = json.dumps({"answers": answers, "reply": text}, ensure_ascii=False)
    if meeting:
        state.update_meeting(meeting["id"], status="held", transcript=transcript, minutes=text)
        return meeting["id"]
    seq = state.next_seq("meeting")
    meeting_id = f"{cfg.meeting_prefix}-{seq:04d}"
    state.insert_meeting(
        {
            "id": meeting_id,
            "seq": seq,
            "type": "standup",
            "when_at": when.astimezone(UTC).isoformat(timespec="seconds"),
            "status": "held",
            "agenda": "ad hoc standup",
            "transcript": transcript,
            "minutes": text,
        }
    )
    return meeting_id


def run_standup(
    cfg: Config,
    state: State,
    llm: LLM,
    answers: dict[str, str] | None = None,
    ask: Callable[[str], str] = input,
) -> str:
    if answers is None:
        print("Standup. Three answers, one line each.")
        answers = {
            "yesterday": ask("Yesterday: "),
            "today": ask("Today: "),
            "blockers": ask("Blockers: "),
        }
    today = datetime.now(cfg.tz)
    prompt = render(
        "standup",
        engineer_name=cfg.engineer_name,
        date=today.strftime("%A %d %B"),
        yesterday=answers["yesterday"] or "(blank)",
        today_plan=answers["today"] or "(blank)",
        blockers=answers["blockers"] or "(none)",
        open_ticket=_open_ticket_line(state, with_brief=True) + _desk_context(cfg, state),
        boss_name=cfg.boss_name,
    )
    reply = llm.ask(system_prompt(cfg, state), prompt, purpose="standup reply", prefer="quality")
    text = (
        reply.text.strip()
        if reply.ok
        else "Noted. I am offline for replies right now; carry on with the ticket."
    )
    record_standup(cfg, state, answers, text)
    return text


def _meeting_system(cfg: Config, state: State, m: dict, llm: LLM | None = None) -> str:
    when_local = parse_iso(m["when_at"]).astimezone(cfg.tz).strftime("%A %d %B, %H:%M")
    if m["type"] == "client_call":
        c = next((c for c in clients.CLIENTS if c["name"] == m["client"]), None)
        if c is None:
            c = {
                "name": m["client"] or "the client",
                "sector": "small business",
                "contact": "the owner",
                "role": "owner",
                "situation": m["agenda"],
                "hidden": [],
            }
        return render(
            "client_call",
            contact_name=c["contact"],
            contact_role=c["role"],
            client_name=c["name"],
            sector=c["sector"],
            company_name=cfg.company,
            engineer_name=cfg.engineer_name,
            situation=c["situation"],
            hidden_facts="\n".join(f"- {h}" for h in c["hidden"]) or "- none",
        )
    level = state.level
    lvl = ladder.get_level(level)
    reviews = state.recent_reviews(3)
    recent = (
        "; ".join(f"{r['ticket_id']} {r['verdict']} {r['score']}/5" for r in reviews) or "none yet"
    )
    gate_qs = (
        progression.gate_questions(cfg, state, llm, level)
        if "Gate probe" in m["agenda"]
        else list(lvl.gate_questions)
    )
    return (
        system_prompt(cfg, state)
        + "\n\n"
        + render(
            "one_on_one",
            engineer_name=cfg.engineer_name,
            meeting_id=m["id"],
            when=when_local,
            agenda=m["agenda"],
            level=level,
            level_name=lvl.name,
            accepted=state.accepted_count(level),
            required=lvl.required_accepted,
            open_ticket=_open_ticket_line(state) + _desk_context(cfg, state),
            recent_reviews=recent,
            gate_questions="\n".join(f"- {q}" for q in gate_qs),
        )
    )


def _for_model(line: str) -> str:
    """The CLI treats a leading slash as a command, so meeting commands are rephrased."""
    if line == "/end":
        return "I have to go now, thanks. Close the meeting in two sentences."
    if line.startswith("/ooc"):
        return f"(Out of character, from the person running this simulation: {line[4:].strip()})"
    if line.startswith("/"):
        return line.lstrip("/")
    return line


def run_meeting(
    cfg: Config,
    state: State,
    llm: LLM,
    meeting_id: str,
    ask: Callable[[str], str] = input,
    say: Callable[[str], None] = print,
) -> dict:
    m = state.get_meeting(meeting_id)
    if m is None:
        raise ValueError(f"unknown meeting {meeting_id}")
    m = dict(m)
    if m["type"] == "standup":
        raise ValueError("standups are async: run `boss standup`")
    system = _meeting_system(cfg, state, m, llm)
    speaker = (
        m["client"].split()[0] if m["type"] == "client_call" and m["client"] else cfg.boss_first
    )
    transcript: list[dict] = []
    reply = llm.quality(
        system,
        "The meeting starts now. Open with your first message.",
        purpose=f"meeting {meeting_id} open",
        persist=True,
    )
    if not reply.ok:
        raise RuntimeError(f"could not open the meeting: {reply.error}")
    session = reply.session_id
    say(f"\n{speaker}: {reply.text.strip()}\n")
    transcript.append({"who": speaker, "text": reply.text.strip()})
    while True:
        try:
            line = ask("you> ").strip()
        except EOFError:
            line = "/end"
        if not line:
            continue
        transcript.append({"who": cfg.engineer_name, "text": line})
        reply = llm.quality(
            system,
            _for_model(line),
            purpose=f"meeting {meeting_id} turn",
            session_id=session,
            persist=True,
        )
        if not reply.ok:
            say(f"[{speaker} dropped off the call: {reply.error}. Say it again or /end.]")
            continue
        session = reply.session_id or session
        say(f"\n{speaker}: {reply.text.strip()}\n")
        transcript.append({"who": speaker, "text": reply.text.strip()})
        if line == "/end":
            break
    text = "\n".join(f"{t['who']}: {t['text']}" for t in transcript)
    minutes_reply = llm.ask(
        system_prompt(cfg, state),
        render(
            "minutes",
            meeting_type=LABEL.get(m["type"], m["type"]),
            meeting_id=meeting_id,
            ticket_id=m.get("ticket_id") or "none",
            boss_name=cfg.boss_name,
            transcript=text[-20000:],
        ),
        purpose=f"minutes {meeting_id}",
    )
    outcome: dict = {}
    if minutes_reply.ok:
        try:
            outcome = extract_json(minutes_reply.text)
        except ValueError:
            outcome = {"minutes_md": minutes_reply.text}
    minutes = str(outcome.get("minutes_md") or "(no minutes)")
    for key in ("notes_for_boss", "follow_up_hint"):
        if outcome.get(key) and str(outcome[key]).strip().lower() not in {"null", "none"}:
            state.add_note(f"1:1 {meeting_id}", str(outcome[key]), m.get("ticket_id"))
    state.update_meeting(
        meeting_id,
        status="held",
        transcript=text,
        minutes=minutes,
        outcome_json=json.dumps(outcome, ensure_ascii=False),
    )
    gate = outcome.get("gate_passed")
    if m["type"] == "one_on_one" and "Gate probe" in m["agenda"] and gate is True:
        state.set_meta(f"gate:L{state.level}", "passed")
        level_up = progression.maybe_level_up(state)
        if level_up:
            outcome["level_up"] = level_up
    elif m["type"] == "one_on_one" and "Gate probe" in m["agenda"] and gate is False:
        state.set_meta(f"gate:L{state.level}", "failed")
    cfg.meetings_dir.mkdir(parents=True, exist_ok=True)
    (cfg.meetings_dir / f"{meeting_id}.md").write_text(
        f"# {LABEL.get(m['type'], m['type'])} {meeting_id}\n\n## Minutes\n\n{minutes}\n\n"
        f"## Transcript\n\n{text}\n",
        encoding="utf-8",
    )
    outcome["minutes_md"] = minutes
    print(f"minutes written to {cfg.meetings_dir / (meeting_id + '.md')}", file=sys.stderr)
    return outcome
