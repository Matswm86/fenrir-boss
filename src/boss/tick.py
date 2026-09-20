"""The scheduler. Runs hourly. Every step is idempotent through state checks or once-keys."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from boss import backup, channels, desk, meetings, progression, publish, tickets
from boss.config import Config
from boss.llm import LLM
from boss.persona import render, system_prompt
from boss.state import State, parse_iso


def in_quiet_hours(local: datetime, cfg: Config) -> bool:
    start, end = cfg.quiet_hours
    hour = local.hour
    return (hour >= start or hour < end) if start > end else (start <= hour < end)


def ticket_message(cfg: Config, row: dict) -> tuple[str, str]:
    spec = row["spec"]
    due_local = parse_iso(row["due_at"]).astimezone(cfg.tz).strftime("%A %d %B, %H:%M")
    subject = f"{row['id']}: {row['title']}"
    brief = spec["brief"].strip()
    body = (
        f"{cfg.engineer_name},\n\n"
        f"New ticket, {row['id']}. Due {due_local}; I have set aside about "
        f"{spec['estimate_hours']:g} hours for it. The sandbox is {row['sandbox']}, and "
        f"TICKET.md there has the acceptance criteria. Hand it in with "
        f'`boss submit {row["id"]} -m "..."` once the tests are green.\n\n{brief}'
    )
    if spec.get("warnings"):
        body += "\n\nOne more thing: " + "; ".join(spec["warnings"]) + "."
    if not brief.rstrip().endswith(cfg.boss_first):
        body += f"\n\n{cfg.boss_first}"
    return subject, body


def _invite(cfg: Config, state: State, m: dict) -> None:
    when_local = parse_iso(m["when_at"]).astimezone(cfg.tz).strftime("%A %d %B, %H:%M")
    label = meetings.LABEL.get(m["type"], m["type"])
    ics_path = cfg.calendar_dir / f"{m['id']}.ics"
    how = (
        "It is async: three lines, any time that day, with `boss standup` or on the desk."
        if m["type"] == "standup"
        else f"Run `boss meet {m['id']}` when it starts and type /end when we are done."
    )
    body = (
        f"{cfg.engineer_name},\n\nI have put a {label.lower()} in your calendar for "
        f"{when_local}. {how}\n\n{m['agenda']}\n\nCalendar file: {ics_path}\n\n{cfg.boss_first}"
    )
    ics = (ics_path.name, ics_path.read_text(encoding="utf-8")) if ics_path.exists() else None
    channels.deliver(
        cfg,
        state,
        kind="invite",
        subject=f"{label}, {when_local}",
        body=body,
        meeting_id=m["id"],
        ics=ics,
        quiet=True,
    )


def tick(
    cfg: Config, state: State, llm: LLM | None, *, now: datetime | None = None, force: bool = False
) -> list[str]:
    now = now or datetime.now(UTC)
    local = now.astimezone(cfg.tz)
    actions: list[str] = []
    if in_quiet_hours(local, cfg) and not force:
        return [f"quiet hours ({local:%H:%M} local): nothing sent"]
    if cfg.section("desk").get("enabled") and cfg.section("web").get("host"):
        try:
            actions.append(desk.sync(cfg, state))
            if llm is not None:
                n = desk.answer_pending(cfg, state, llm)
                if n:
                    actions.append(f"answered {n} desk item(s)")
        except Exception as exc:  # noqa: BLE001 - the desk must never break the tick
            actions.append(f"desk skipped: {type(exc).__name__}")

    for m in meetings.plan_week(cfg, state, now):
        _invite(cfg, state, m)
        actions.append(f"scheduled {m['id']} {m['type']} at {m['when_at']}")

    level = state.level
    if progression.needs_gate_meeting(state, level):
        for m in state.meetings(status="scheduled"):
            if (
                m["type"] == "one_on_one"
                and "Gate probe" not in m["agenda"]
                and parse_iso(m["when_at"]) > now
            ):
                agenda = m["agenda"] + (
                    f" Gate probe: you have enough accepted tickets at L{level}; "
                    "I ask the gate questions and decide whether you move up."
                )
                state.update_meeting(m["id"], agenda=agenda)
                if state.once(f"gate-note:{m['id']}"):
                    channels.deliver(
                        cfg,
                        state,
                        kind="note",
                        subject=f"Gate questions in our next 1:1 ({m['id']})",
                        body=(
                            f"{cfg.engineer_name},\n\nYou have the accepted tickets for "
                            f"L{level} now, so I have added the gate questions to our 1:1 "
                            f"{m['id']}. Pass them and you move up a level. Prepare.\n\n"
                            f"{cfg.boss_first}"
                        ),
                        meeting_id=m["id"],
                    )
                    actions.append(f"gate probe added to {m['id']}")

    for m, kind in meetings.due(cfg, state, now):
        when_local = parse_iso(m["when_at"]).astimezone(cfg.tz).strftime("%A %H:%M")
        label = meetings.LABEL.get(m["type"], m["type"])
        if kind == "agenda":
            how = (
                "Three lines with `boss standup` or on the desk."
                if m["type"] == "standup"
                else f"`boss meet {m['id']}` when you are ready."
            )
            channels.deliver(
                cfg,
                state,
                kind="agenda",
                subject=f"{label} now ({when_local})",
                body=(
                    f"{cfg.engineer_name},\n\n{label} is now. {how}\n\n{m['agenda']}\n\n"
                    f"{cfg.boss_first}"
                ),
                meeting_id=m["id"],
                quiet=True,
            )
            state.update_meeting(m["id"], status="notified")
        else:
            channels.deliver(
                cfg,
                state,
                kind="reminder",
                subject=f"{label} tomorrow at {when_local}",
                body=(
                    f"{cfg.engineer_name},\n\nReminder, {label.lower()} tomorrow at "
                    f"{when_local}. {m['agenda']}\n\n{cfg.boss_first}"
                ),
                meeting_id=m["id"],
                quiet=True,
            )
        actions.append(f"{kind} sent for {m['id']}")

    if not state.open_tickets():
        last = state.last_ticket_created()
        gap = timedelta(hours=float(cfg.section("rules").get("min_hours_between_tickets", 20)))
        if force or last is None or now - last >= gap:
            try:
                row = tickets.generate(cfg, state, llm)
            except tickets.TicketError as exc:
                actions.append(f"ticket generation failed: {exc}")
            else:
                subject, body = ticket_message(cfg, row)
                channels.deliver(
                    cfg, state, kind="ticket", subject=subject, body=body, ticket_id=row["id"]
                )
                actions.append(f"assigned {row['id']} {row['title']} ({row['source']})")
                m = meetings.schedule_from_spec(cfg, state, row, now)
                if m:
                    _invite(cfg, state, m)
                    actions.append(f"scheduled {m['id']} {m['type']} for {row['id']}")
        else:
            wait = gap - (now - last)
            actions.append(
                f"no open ticket; next one in about {int(wait.total_seconds() // 3600)} h"
            )

    for t in state.open_tickets():
        due_at = parse_iso(t["due_at"])
        if now > due_at and state.once(f"nudge:{t['id']}:{local.date()}"):
            overdue = max(1, (now - due_at).days)
            text = None
            if llm is not None:
                reply = llm.ask(
                    system_prompt(cfg, state),
                    render(
                        "nudge",
                        ticket_id=t["id"],
                        title=t["title"],
                        client=t["client"],
                        due=due_at.astimezone(cfg.tz).strftime("%A %H:%M"),
                        overdue=overdue,
                        boss_name=cfg.boss_name,
                        engineer_name=cfg.engineer_name,
                    ),
                    purpose=f"nudge {t['id']}",
                    prefer="cheap",
                )
                text = reply.text.strip() if reply.ok else None
            text = text or (
                f"{cfg.engineer_name},\n\n{t['id']} was due {due_at.astimezone(cfg.tz):%A %H:%M} "
                "and I have nothing from you. What is blocking? If the scope is wrong, say so "
                f"and we cut it. Hand it in with `boss submit {t['id']}` when it is green.\n\n"
                f"{cfg.boss_first}"
            )
            channels.deliver(
                cfg,
                state,
                kind="nudge",
                subject=f"{t['id']} is late",
                body=text,
                ticket_id=t["id"],
            )
            actions.append(f"nudged {t['id']}")
    if state.once(f"backup:{local.date()}"):
        try:
            actions.append(backup.run(cfg, state))
        except Exception as exc:  # noqa: BLE001 - a failed backup is reported, never fatal
            actions.append(f"backup failed: {type(exc).__name__}")
    if cfg.section("web").get("enabled"):
        try:
            actions.append(publish.publish(cfg, state, timeout=45))
        except Exception as exc:  # noqa: BLE001 - publishing must never break the tick
            actions.append(f"publish skipped: {type(exc).__name__}")
    return actions or ["nothing to do"]
