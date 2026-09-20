"""The desk: a small web page with your ticket, a thread with the boss, a thread with the
tutor, standups and notes. `boss desk` serves it on localhost.

Three parts in one module, because they share one data shape:

1. `bundle()` is the JSON the page reads: tickets with their briefs, acceptance criteria and
   test names, the inbox, reviews, meetings, the ladder and the handbook. Home-directory
   paths are folded to `~` first.
2. `Desk` holds the request handlers behind `/api/`. It stores what the learner writes
   (questions, standups, notes) as events in an outbox of JSON lines; it never answers
   by itself.
3. `ingest()` queues those events in the state database and `answer_pending()` answers them
   with the same model and memory as reviews and 1:1s: one voice. Locally the server does
   both right after each post; on a self-hosted server (docs/SELF-HOSTING.md) the tick on
   your own machine pulls the outbox with `sync()` and publishes the answers back.

Nothing here writes the learner's code. Every reply runs through the code stripper anyway.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

from boss import ladder, meetings, safety
from boss.config import Config
from boss.persona import render, system_prompt
from boss.state import State, now_iso, parse_iso

HOME_RE = re.compile(r"/home/[a-z0-9_-]+/")
TEST_NAME_RE = re.compile(r"^def (test_\w+)", re.M)
MAX_BODY = 64_000
MAX_QUESTION = 4_000
HISTORY_TURNS = 6
WHO_BOSS = "boss"
WHO_TUTOR = "tutor"

OFFLINE_BOSS = "Noted. I am offline for replies right now; carry on with the ticket."
ETA_TEXT = "The answer arrives on this page; outside quiet hours, usually within minutes."
QUEUED_KINDS = frozenset({"boss_question", "standup", "note", "tutor_question"})


def tutor_name(cfg: Config) -> str:
    return str(cfg.section("tutor").get("name") or "Tutor")


def tutor_system(cfg: Config) -> str:
    return (
        f"You are {tutor_name(cfg)}, a tutor in study mode. You explain and quiz; you never "
        "write, fix or complete the learner's code. No em dash, no emoji, no praise words."
    )


def tutor_prompt(
    cfg: Config, state: State, ticket: dict | None, question: str, history: str
) -> str:
    """The strong tutor's user prompt: study-mode rules, the ticket for context, real material."""
    from boss import corpus

    return render(
        "tutor",
        engineer_name=cfg.engineer_name,
        company_name=cfg.company,
        tutor_name=tutor_name(cfg),
        boss_first=cfg.boss_first,
        ticket_context=tutor_context(ticket),
        corpus_block=corpus.block(cfg, question, k=3, chars=400) or "(nothing retrieved)",
        history=("Earlier in this thread:\n" + history) if history else "",
        question=question,
    )


OFFLINE_TUTOR = "The tutor is not answering right now. Re-read the failing test, then try again."


def fold_home(text: str) -> str:
    return HOME_RE.sub("~/", text)


def _read(path: Path, cap: int = 40_000) -> str:
    try:
        return path.read_text(encoding="utf-8")[:cap]
    except (FileNotFoundError, UnicodeDecodeError, PermissionError):
        return ""


# --- 1. the bundle -----------------------------------------------------------------------


def _ticket_dict(cfg: Config, t: dict, now: datetime) -> dict:
    sandbox = Path(t["sandbox"])
    tests_dir = sandbox / "tests"
    test_files = sorted(p.name for p in tests_dir.glob("test_*.py")) if tests_dir.is_dir() else []
    test_names: list[str] = []
    for name in test_files:
        test_names += TEST_NAME_RE.findall(_read(tests_dir / name))
    src_dir = sandbox / "src"
    src_files = (
        sorted(p.relative_to(sandbox).as_posix() for p in src_dir.rglob("*.py"))
        if src_dir.is_dir()
        else []
    )
    try:
        acceptance = json.loads(t["acceptance"] or "[]")
    except json.JSONDecodeError:
        acceptance = []
    due = parse_iso(t["due_at"])
    return {
        "id": t["id"],
        "title": t["title"],
        "client": t["client"],
        "status": t["status"],
        "kind": t["kind"],
        "level": t["level"],
        "created_at": t["created_at"],
        "due_at": t["due_at"],
        "due_local": due.astimezone(cfg.tz).strftime("%a %d %b %H:%M"),
        "overdue": t["status"] in {"open", "changes_requested"} and now > due,
        "sandbox": fold_home(t["sandbox"]),
        "brief": fold_home(t["brief"]),
        "acceptance": [fold_home(str(a)) for a in acceptance],
        "run_command": t["run_command"] or "uv run pytest -q",
        "ticket_md": fold_home(_read(sandbox / "TICKET.md")),
        "test_files": test_files,
        "test_names": test_names,
        "src_files": src_files,
    }


def needs_you(cfg: Config, state: State, now: datetime) -> list[dict]:
    """What waits on the engineer right now: the desk's approval inbox, one human, one boss."""
    items: list[dict] = []
    local_today = now.astimezone(cfg.tz).date()
    for t in state.open_tickets():
        due = parse_iso(t["due_at"])
        if t["status"] == "changes_requested":
            r = next((r for r in state.recent_reviews(10) if r["ticket_id"] == t["id"]), None)
            items.append(
                {
                    "kind": "rework",
                    "tab": "ticket",
                    "text": f"{t['id']} came back: {r['summary'] if r else 'changes requested'}",
                    "cmd": f'boss submit {t["id"]} -m "..."',
                }
            )
        elif now > due:
            hours = int((now - due).total_seconds() // 3600)
            items.append(
                {
                    "kind": "overdue",
                    "tab": "ticket",
                    "text": f"{t['id']} is {hours} h overdue. Hand it in or say why.",
                    "cmd": f'boss submit {t["id"]} -m "..."',
                }
            )
        else:
            items.append(
                {
                    "kind": "ticket",
                    "tab": "ticket",
                    "text": f"{t['id']} {t['title']}, due {due.astimezone(cfg.tz):%a %H:%M}",
                    "cmd": t["run_command"] or "uv run pytest -q",
                }
            )
    for m in state.meetings():
        if m["status"] not in {"scheduled", "notified"}:
            continue
        when = parse_iso(m["when_at"])
        local = when.astimezone(cfg.tz)
        if m["type"] == "standup" and local.date() == local_today:
            items.append(
                {
                    "kind": "standup",
                    "tab": "standup",
                    "text": f"Standup today ({m['id']}). Three lines.",
                    "cmd": "boss standup",
                }
            )
        elif m["type"] != "standup" and 0 <= (when - now).total_seconds() <= 26 * 3600:
            label = meetings.LABEL.get(m["type"], m["type"])
            items.append(
                {
                    "kind": "meeting",
                    "tab": "inbox",
                    "text": f"{label} {local:%a %H:%M} ({m['id']}). Terminal only.",
                    "cmd": f"boss meet {m['id']}",
                }
            )
    return items


def progress(cfg: Config, state: State, now: datetime) -> dict:
    rows = state.meetings()
    past = [
        m
        for m in rows
        if m["type"] == "standup"
        and parse_iso(m["when_at"]) <= now
        and m["status"] in {"held", "missed"}
    ]
    streak = 0
    for m in reversed(past):
        if m["status"] != "held":
            break
        streak += 1
    done = [t for t in state.tickets() if t["status"] == "done"]
    reviews = state.recent_reviews(50)
    first = state.conn.execute("SELECT MIN(reached_at) AS a FROM level_history").fetchone()
    started = parse_iso(first["a"]) if first and first["a"] else now
    return {
        "tickets_done": len(done),
        "reviews": len(reviews),
        "approved": sum(1 for r in reviews if r["verdict"] == "APPROVED"),
        "standups_held": sum(1 for m in past if m["status"] == "held"),
        "standups_missed": sum(1 for m in past if m["status"] == "missed"),
        "standup_streak": streak,
        "days_in": max(0, (now - started).days),
    }


def bundle(cfg: Config, state: State, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    level = state.level
    lvl = ladder.get_level(level)
    boss = cfg.section("boss")
    return {
        "needs_you": needs_you(cfg, state, now),
        "progress": progress(cfg, state, now),
        "answers": state.desk_answers(),
        "pending": [r["id"] for r in state.pending_desk_questions(50)],
        "eta": ETA_TEXT,
        "rendered": now.isoformat(timespec="seconds"),
        "company": cfg.company,
        "boss_name": cfg.boss_name,
        "boss_first": cfg.boss_first,
        "boss_title": boss.get("title", "Head of Engineering"),
        "tutor_name": tutor_name(cfg),
        "engineer_name": cfg.engineer_name,
        "timezone": str(cfg.tz),
        "level": level,
        "level_name": lvl.name,
        "competencies": list(lvl.competencies),
        "ladder": [
            {
                "number": lv.number,
                "name": lv.name,
                "phase": lv.phase,
                "accepted": state.accepted_count(lv.number),
                "required": lv.required_accepted,
                "current": lv.number == level,
            }
            for lv in ladder.LEVELS
        ],
        "tickets": [_ticket_dict(cfg, dict(t), now) for t in state.tickets()],
        "open": [t["id"] for t in state.open_tickets()],
        "meetings": [
            {
                "id": m["id"],
                "type": m["type"],
                "label": meetings.LABEL.get(m["type"], m["type"]),
                "when_at": m["when_at"],
                "when_local": parse_iso(m["when_at"]).astimezone(cfg.tz).strftime("%a %d %b %H:%M"),
                "status": m["status"],
                "agenda": m["agenda"],
                "client": m["client"],
                "minutes": fold_home(m["minutes"] or ""),
            }
            for m in state.meetings()
        ],
        "reviews": [
            {
                "ticket_id": r["ticket_id"],
                "verdict": r["verdict"],
                "score": r["score"],
                "summary": r["summary"],
                "feedback_md": fold_home(r["feedback_md"] or ""),
                "next_focus": r["next_focus"],
                "created_at": r["created_at"],
            }
            for r in state.recent_reviews(20)
        ],
        "messages": [
            {
                "kind": m["kind"],
                "subject": m["subject"],
                "body": fold_home(m["body"]),
                "created_at": m["created_at"],
                "ticket_id": m["ticket_id"],
            }
            for m in state.messages(30)
        ],
        "handbook": _read(cfg.root / "company" / "HANDBOOK.md"),
        "llm_today": {
            "quality_calls": state.quality_calls_today(),
            "spend_usd": round(state.spend_today(), 2),
        },
    }


# --- outbox: what happened on the web ----------------------------------------------------


def append_event(outbox_dir: Path, event: dict) -> dict:
    event.setdefault("id", uuid4().hex)
    event.setdefault("at", now_iso())
    outbox_dir.mkdir(parents=True, exist_ok=True)
    path = outbox_dir / f"{event['at'][:10]}.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def read_events(*dirs: Path) -> list[dict]:
    events: list[dict] = []
    for d in dirs:
        if not d.is_dir():
            continue
        for path in sorted(d.glob("*.jsonl")):
            for line in _read(path, cap=10_000_000).splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(ev, dict) and ev.get("id") and ev.get("kind"):
                    events.append(ev)
    events.sort(key=lambda e: str(e.get("at", "")))
    return events


def activity(events: list[dict]) -> dict:
    """Group events the way the page shows them: one thread per ticket, standups, notes."""
    threads: dict[str, list[dict]] = {}
    standups: list[dict] = []
    notes: list[dict] = []
    for ev in events:
        kind = ev["kind"]
        if kind in {"boss_question", "tutor_question"}:
            thread = threads.setdefault(ev.get("ticket") or "general", [])
            thread.append(
                {
                    "id": ev["id"],
                    "who": "you",
                    "channel": WHO_BOSS if kind == "boss_question" else WHO_TUTOR,
                    "text": ev["question"],
                    "at": ev["at"],
                    "pending": True,
                }
            )
        elif kind in {"boss_chat", "tutor_chat"}:
            who = WHO_BOSS if kind == "boss_chat" else WHO_TUTOR
            thread = threads.setdefault(ev.get("ticket") or "general", [])
            thread.append({"who": "you", "channel": who, "text": ev["question"], "at": ev["at"]})
            thread.append({"who": who, "channel": who, "text": ev["reply"], "at": ev["at"]})
        elif kind == "standup":
            standups.append(
                {"id": ev["id"], "at": ev["at"], "answers": ev["answers"], "reply": ev.get("reply")}
            )
        elif kind == "note":
            notes.append(
                {"id": ev["id"], "at": ev["at"], "text": ev["text"], "reply": ev.get("reply")}
            )
    return {"threads": threads, "standups": standups, "notes": notes}


def thread_context(
    cfg: Config, state: State, ticket_id: str | None, limit: int = HISTORY_TURNS
) -> str:
    """The last exchanges on the desk for a ticket (answered questions plus terminal `boss ask`
    and `boss help`), for the prompts that follow."""
    items: list[tuple[str, str, str]] = []  # (at, who, text pairs joined)
    for r in state.answered_desk_questions(200):
        if r["kind"] not in {"boss_question", "tutor_question"}:
            continue
        if ticket_id and r["ticket_id"] != ticket_id:
            continue
        q = json.loads(r["payload_json"]).get("question", "")
        who = cfg.boss_first if r["kind"] == "boss_question" else tutor_name(cfg)
        items.append((r["answered_at"] or r["at"], who, f"{q}\x00{r['answer']}"))
    for e in read_events(cfg.root / "desk" / "local", cfg.root / "desk" / "outbox"):
        if e["kind"] not in {"boss_chat", "tutor_chat"}:
            continue
        if ticket_id and e.get("ticket") != ticket_id:
            continue
        who = cfg.boss_first if e["kind"] == "boss_chat" else tutor_name(cfg)
        items.append((e["at"], who, f"{e['question']}\x00{e['reply']}"))
    items.sort(key=lambda t: t[0])
    lines = []
    for _, who, pair in items[-limit:]:
        q, a = pair.split("\x00", 1)
        lines.append(f"{cfg.engineer_name} asked: {q[:300]}")
        lines.append(f"{who}: {a[:300]}")
    return "\n".join(lines)


# --- the tutor: help without code -------------------------------------------------------


def tutor_context(ticket: dict | None) -> str:
    if not ticket:
        return "The learner has no open ticket right now."
    crit = "\n".join(f"- {a}" for a in ticket.get("acceptance", [])) or "- (none listed)"
    tests = ", ".join(ticket.get("test_names", [])) or "(none)"
    return (
        f'The learner works on a sandbox ticket {ticket["id"]} "{ticket["title"]}" from a '
        f"fictional workplace exercise. Brief:\n{ticket.get('brief', '')[:1500]}\n\n"
        f"Acceptance criteria:\n{crit}\n\nTests they must make pass: {tests}. "
        "Help them understand the concept and the failing test; never write the code."
    )


# --- 2. the service behind /api/ ----------------------------------------------------------------


class Desk:
    """Request handlers. They store events and never answer; `on_event` wakes the
    local answer worker."""

    def __init__(
        self,
        cfg: Config,
        *,
        data_dir: Path,
        bundle_path: Path,
        on_event=None,
    ):
        self.cfg = cfg
        self.data_dir = data_dir
        self.outbox = data_dir / "outbox"
        self.bundle_path = bundle_path
        self.on_event = on_event
        self.refresh = None

    def _emit(self, event: dict) -> dict:
        ev = append_event(self.outbox, event)
        if self.on_event is not None:
            self.on_event()
        return ev

    # data
    def bundle(self) -> dict:
        try:
            return json.loads(self.bundle_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {"tickets": [], "open": []}

    def ticket(self, ticket_id: str | None) -> dict | None:
        b = self.bundle()
        tickets = {t["id"]: t for t in b.get("tickets", [])}
        if ticket_id and ticket_id in tickets:
            return tickets[ticket_id]
        for tid in b.get("open", []):
            if tid in tickets:
                return tickets[tid]
        return None

    def history(self, ticket_id: str, kind: str) -> list[dict]:
        events = [
            e
            for e in read_events(self.outbox)
            if e["kind"] == kind and e.get("ticket") == ticket_id
        ][-HISTORY_TURNS:]
        out: list[dict] = []
        for e in events:
            out.append({"role": "user", "content": e["question"]})
            out.append({"role": "assistant", "content": e["reply"]})
        return out

    # handlers
    def handle(self, method: str, path: str, body: dict) -> tuple[int, dict]:
        route = (method, path.rstrip("/") or "/")
        if route == ("GET", "/health"):
            return 200, {
                "status": "ok",
                "bundle": self.bundle_path.exists(),
                "events": len(read_events(self.outbox)),
            }
        if route == ("GET", "/activity"):
            return 200, activity(read_events(self.outbox))
        if route == ("POST", "/ask-boss"):
            return self.ask_boss(body)
        if route == ("POST", "/ask-tutor"):
            return self.ask_tutor(body)
        if route == ("POST", "/standup"):
            return self.standup(body)
        if route == ("POST", "/note"):
            return self.note(body)
        return 404, {"error": "no such route"}

    @staticmethod
    def _text(body: dict, key: str, cap: int = MAX_QUESTION) -> str:
        return str(body.get(key) or "").strip()[:cap]

    def _ticket_line(self, t: dict | None) -> str:
        if not t:
            return "none"
        return (
            f"{t['id']} {t['title']} ({t['client']}), status {t['status']}, due {t['due_local']}"
            "\nThe brief, so you only refer to what the ticket says:\n" + t["brief"][:1200]
        )

    def ask_boss(self, body: dict) -> tuple[int, dict]:
        question = self._text(body, "question")
        if not question:
            return 400, {"error": "missing question"}
        t = self.ticket(body.get("ticket"))
        ticket_id = t["id"] if t else "general"
        ev = self._emit({"kind": "boss_question", "ticket": ticket_id, "question": question})
        return 200, {
            "queued": True,
            "id": ev["id"],
            "at": ev["at"],
            "who": WHO_BOSS,
            "eta": ETA_TEXT,
        }

    def ask_tutor(self, body: dict) -> tuple[int, dict]:
        """The strong tutor: queued, answered by the tick with the quality model in study mode."""
        question = self._text(body, "question")
        if not question:
            return 400, {"error": "missing question"}
        t = self.ticket(body.get("ticket"))
        ev = self._emit(
            {"kind": "tutor_question", "ticket": t["id"] if t else "general", "question": question},
        )
        return 200, {
            "queued": True,
            "id": ev["id"],
            "at": ev["at"],
            "who": WHO_TUTOR,
            "eta": ETA_TEXT,
        }

    def standup(self, body: dict) -> tuple[int, dict]:
        answers = {k: self._text(body, k, 1000) for k in ("yesterday", "today", "blockers")}
        if not any(answers.values()):
            return 400, {"error": "three empty answers is not a standup"}
        t = self.ticket(None)
        ev = self._emit({"kind": "standup", "ticket": t["id"] if t else None, "answers": answers})
        return 200, {"queued": True, "id": ev["id"], "at": ev["at"], "eta": ETA_TEXT}

    def note(self, body: dict) -> tuple[int, dict]:
        text_in = self._text(body, "text")
        if not text_in:
            return 400, {"error": "empty note"}
        t = self.ticket(None)
        ev = self._emit({"kind": "note", "ticket": t["id"] if t else None, "text": text_in})
        return 200, {"queued": True, "id": ev["id"], "at": ev["at"], "eta": ETA_TEXT}


# --- HTTP server (stdlib) -------------------------------------------------------------------

RATE_LIMIT = (20, 60.0)  # requests per window per client for POST routes
_buckets: dict[str, deque] = {}
_lock = threading.Lock()


def _rate_ok(client: str) -> bool:
    limit, window = RATE_LIMIT
    now = time.monotonic()
    with _lock:
        bucket = _buckets.setdefault(client, deque())
        while bucket and bucket[0] < now - window:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True


MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
}


def make_handler(desk: Desk, site_dir: Path | None = None):
    """site_dir set = local mode: static files from it, the API under /api/. Without it the
    handler is API-only and a reverse proxy strips the /api prefix (self-hosting)."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "fenrir-boss-desk"

        def log_message(self, fmt: str, *args) -> None:  # noqa: A002 - stdlib signature
            print(f"{self.client_address[0]} {fmt % args}", file=sys.stderr)

        def _client(self) -> str:
            return (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0]

        def _send(self, status: int, payload: dict) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _static(self, path: str) -> None:
            """Local mode: the page and its bundle come from <root>/site, nothing else."""
            if path in {"", "/"}:
                self.send_response(302)
                self.send_header("Location", "/desk/")
                self.end_headers()
                return
            if path == "/desk/bundle.json" and desk.refresh is not None:
                desk.refresh()
            rel = path.lstrip("/") + ("index.html" if path.endswith("/") else "")
            target = (site_dir / rel).resolve()
            if site_dir.resolve() not in target.parents or not target.is_file():
                self._send(404, {"error": "not found"})
                return
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", MIME.get(target.suffix, "application/octet-stream"))
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _api_path(self) -> str | None:
            path = self.path.split("?", 1)[0]
            if site_dir is None:
                return path
            return path[4:] or "/" if path.startswith("/api/") or path == "/api" else None

        def do_GET(self) -> None:  # noqa: N802 - stdlib name
            path = self._api_path()
            if path is None:
                self._static(self.path.split("?", 1)[0])
                return
            status, payload = desk.handle("GET", path, {})
            self._send(status, payload)

        def do_POST(self) -> None:  # noqa: N802 - stdlib name
            if not _rate_ok(self._client()):
                self._send(429, {"error": "slow down"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                self._send(413, {"error": "body too large"})
                return
            raw = self.rfile.read(length) if length else b""
            try:
                body = json.loads(raw.decode("utf-8")) if raw else {}
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._send(400, {"error": "invalid JSON"})
                return
            if not isinstance(body, dict):
                self._send(400, {"error": "body must be an object"})
                return
            try:
                status, payload = desk.handle("POST", self._api_path() or "/", body)
            except Exception as exc:  # noqa: BLE001 - one bad request must not kill the server
                print(f"desk error: {type(exc).__name__}: {exc}", file=sys.stderr)
                status, payload = 500, {"error": type(exc).__name__}
            self._send(status, payload)

    return Handler


def _answer_worker(cfg: Config, wake: threading.Event) -> None:
    """Local mode: after each post, queue it and answer it, in this thread with its own
    database handle (SQLite connections are bound to the thread that opened them)."""
    from boss import publish
    from boss.llm import LLM

    while True:
        wake.wait()
        wake.clear()
        state = State(cfg.db_path)
        try:
            ingest(cfg, state, cfg.root / "desk" / "outbox")
            llm = LLM(cfg, state)
            if llm.available():
                answer_pending(cfg, state, llm)
            publish.write_site(cfg, state)
        except Exception as exc:  # noqa: BLE001 - the worker must outlive one bad event
            print(f"desk worker: {type(exc).__name__}: {exc}", file=sys.stderr)
        finally:
            state.close()


def serve(cfg: Config, state: State, *, local: bool = True) -> None:
    """local=True (`boss desk`): page + API on localhost, answers within the minute.
    local=False (`boss desk-serve` on your own server): API only, behind a reverse proxy
    that handles login; the tick on your machine syncs and answers."""
    from boss import publish

    d = cfg.section("desk")
    port = int(os.environ.get("DESK_PORT") or d.get("port", 8110))
    host = os.environ.get("DESK_HOST") or "127.0.0.1"
    if local:
        data_dir = cfg.root / "desk"
        site = publish.write_site(cfg, state)
        wake = threading.Event()
        desk = Desk(
            cfg, data_dir=data_dir, bundle_path=site / "desk" / "bundle.json", on_event=wake.set
        )

        def refresh() -> None:
            fresh = State(cfg.db_path)
            try:
                publish.write_site(cfg, fresh)
            finally:
                fresh.close()

        desk.refresh = refresh
        threading.Thread(target=_answer_worker, args=(cfg, wake), daemon=True).start()
        handler = make_handler(desk, site)
    else:
        data_dir = Path(os.environ.get("DESK_DATA") or cfg.root)
        bundle_path = Path(
            os.environ.get("DESK_BUNDLE") or (cfg.root / "site" / "desk" / "bundle.json")
        )
        desk = Desk(cfg, data_dir=data_dir, bundle_path=bundle_path)
        handler = make_handler(desk)
    (data_dir / "outbox").mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((host, port), handler)
    where = f"http://{host}:{port}" + ("/desk/" if local else "")
    print(f"desk on {where} (Ctrl+C to stop)", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


# --- 3. local side: pull the outbox, record it --------------------------------------------


def ingest(cfg: Config, state: State, outbox_dir: Path) -> dict[str, int]:
    """Record new desk events in the state database. Idempotent per event id."""
    from boss import channels

    counts = {"standup": 0, "note": 0, "chat": 0}
    threads_dir = cfg.root / "desk" / "threads"
    counts["queued"] = 0
    for ev in read_events(outbox_dir):
        if not state.once(f"desk:{ev['id']}"):
            continue
        kind = ev["kind"]
        when = parse_iso(ev["at"]) if ev.get("at") else datetime.now(UTC)
        if kind in QUEUED_KINDS and "reply" not in ev:
            if state.add_desk_question(ev):
                counts["queued"] += 1
            continue
        if kind == "standup":
            meetings.record_standup(cfg, state, ev["answers"], ev["reply"], when=when)
            a = ev["answers"]
            channels.deliver(
                cfg,
                state,
                kind="standup",
                subject=f"Standup from the desk, {when.astimezone(cfg.tz):%a %d %b}",
                body=(
                    f"Yesterday: {a.get('yesterday') or '(blank)'}\n"
                    f"Today: {a.get('today') or '(blank)'}\n"
                    f"Blockers: {a.get('blockers') or '(none)'}\n\n"
                    f"{cfg.boss_first}: {ev['reply']}"
                ),
                ticket_id=ev.get("ticket"),
                quiet=True,
            )
            counts["standup"] += 1
        elif kind == "note":
            channels.deliver(
                cfg,
                state,
                kind="desk-note",
                subject=f"Note from {cfg.engineer_name} on the desk",
                body=f"{cfg.engineer_name}: {ev['text']}\n\n{cfg.boss_first}: {ev['reply']}",
                ticket_id=ev.get("ticket"),
                quiet=True,
            )
            log = cfg.root / "company" / "DECISIONS.md"
            log.parent.mkdir(parents=True, exist_ok=True)
            if not log.exists():
                log.write_text(
                    f"# Decisions\n\nWhat {cfg.boss_first} granted or refused outside meetings, "
                    "so neither of us re-argues it.\n",
                    encoding="utf-8",
                )
            with log.open("a", encoding="utf-8") as fh:
                fh.write(
                    f"\n## {when.astimezone(cfg.tz):%Y-%m-%d %H:%M}"
                    f"{' (' + ev['ticket'] + ')' if ev.get('ticket') else ''}\n\n"
                    f"**Asked:** {ev['text']}\n\n**{cfg.boss_first}:** {ev['reply']}\n"
                )
            counts["note"] += 1
        elif kind in {"boss_chat", "tutor_chat"}:
            threads_dir.mkdir(parents=True, exist_ok=True)
            who = cfg.boss_first if kind == "boss_chat" else tutor_name(cfg)
            with (threads_dir / f"{ev.get('ticket') or 'general'}.md").open(
                "a", encoding="utf-8"
            ) as fh:
                fh.write(
                    f"\n## {when.astimezone(cfg.tz):%Y-%m-%d %H:%M} ({who})\n\n"
                    f"**{cfg.engineer_name}:** {ev['question']}\n\n**{who}:** {ev['reply']}\n"
                )
            counts["chat"] += 1
    return counts


def _side_effects(cfg: Config, state: State, row, answer: str) -> None:
    from boss import channels

    payload = json.loads(row["payload_json"])
    when = parse_iso(row["at"])
    if row["kind"] in {"boss_question", "tutor_question"}:
        who = cfg.boss_first if row["kind"] == "boss_question" else tutor_name(cfg)
        threads_dir = cfg.root / "desk" / "threads"
        threads_dir.mkdir(parents=True, exist_ok=True)
        with (threads_dir / f"{row['ticket_id'] or 'general'}.md").open(
            "a", encoding="utf-8"
        ) as fh:
            fh.write(
                f"\n## {when.astimezone(cfg.tz):%Y-%m-%d %H:%M} ({who})\n\n"
                f"**{cfg.engineer_name}:** {payload.get('question', '')}\n\n"
                f"**{who}:** {answer}\n"
            )
    elif row["kind"] == "standup":
        a = payload.get("answers", {})
        meetings.record_standup(cfg, state, a, answer, when=when)
        channels.deliver(
            cfg,
            state,
            kind="standup",
            subject=f"Re: standup {when.astimezone(cfg.tz):%A}",
            body=(
                f"Yesterday: {a.get('yesterday') or '(blank)'}\n"
                f"Today: {a.get('today') or '(blank)'}\n"
                f"Blockers: {a.get('blockers') or '(none)'}\n\n{answer}"
            ),
            ticket_id=row["ticket_id"],
            quiet=True,
        )
    elif row["kind"] == "note":
        channels.deliver(
            cfg,
            state,
            kind="desk-note",
            subject="Re: your note from the desk",
            body=f"{cfg.engineer_name}: {payload.get('text', '')}\n\n{answer}",
            ticket_id=row["ticket_id"],
            quiet=True,
        )
        log = cfg.root / "company" / "DECISIONS.md"
        log.parent.mkdir(parents=True, exist_ok=True)
        if not log.exists():
            log.write_text(
                f"# Decisions\n\nWhat {cfg.boss_first} granted or refused outside meetings, "
                "so neither of us re-argues it.\n",
                encoding="utf-8",
            )
        with log.open("a", encoding="utf-8") as fh:
            fh.write(
                f"\n## {when.astimezone(cfg.tz):%Y-%m-%d %H:%M}"
                f"{' (' + row['ticket_id'] + ')' if row['ticket_id'] else ''}\n\n"
                f"**Asked:** {payload.get('text', '')}\n\n**{cfg.boss_first}:** {answer}\n"
            )


def answer_pending(cfg: Config, state: State, llm, limit: int = 4) -> int:
    """Answer queued desk questions with the same model and memory as her reviews and 1:1s.
    Unanswerable ones (cap reached, model down) stay queued for the next tick."""
    answered = 0
    for row in state.pending_desk_questions(limit):
        payload = json.loads(row["payload_json"])
        rows = [
            t for t in state.open_tickets() if t["id"] == row["ticket_id"]
        ] or state.open_tickets()
        t = _ticket_dict(cfg, dict(rows[0]), datetime.now(UTC)) if rows else None
        line = (
            f"{t['id']} {t['title']} ({t['client']}), status {t['status']}, due {t['due_local']}"
            "\nThe brief, so you only refer to what the ticket says:\n" + t["brief"][:1200]
            if t
            else "none"
        )
        when_local = parse_iso(row["at"]).astimezone(cfg.tz)
        if row["kind"] == "boss_question":
            earlier = thread_context(cfg, state, row["ticket_id"])
            prompt = render(
                "desk",
                tutor_name=tutor_name(cfg),
                engineer_name=cfg.engineer_name,
                boss_name=cfg.boss_name,
                ticket_id=t["id"] if t else "none",
                title=t["title"] if t else "no open ticket",
                client=t["client"] if t else "",
                status=t["status"] if t else "",
                due=t["due_local"] if t else "",
                brief=(t["brief"][:1500] if t else "(no ticket)"),
                acceptance="\n".join(f"- {a}" for a in (t["acceptance"] if t else []))
                or "- (none)",
                history=("Earlier in this thread:\n" + earlier) if earlier else "",
                question=payload.get("question", ""),
            )
        elif row["kind"] == "tutor_question":
            prompt = tutor_prompt(
                cfg,
                state,
                t,
                payload.get("question", ""),
                thread_context(cfg, state, row["ticket_id"]),
            )
        elif row["kind"] == "standup":
            a = payload.get("answers", {})
            prompt = render(
                "standup",
                engineer_name=cfg.engineer_name,
                date=when_local.strftime("%A %d %B"),
                yesterday=a.get("yesterday") or "(blank)",
                today_plan=a.get("today") or "(blank)",
                blockers=a.get("blockers") or "(none)",
                open_ticket=line,
                boss_name=cfg.boss_name,
            )
        else:
            prompt = render(
                "desk_note",
                engineer_name=cfg.engineer_name,
                boss_name=cfg.boss_name,
                text=payload.get("text", ""),
                open_ticket=line,
            )
        system = tutor_system(cfg) if row["kind"] == "tutor_question" else system_prompt(cfg, state)
        reply = llm.ask(system, prompt, purpose=f"desk {row['kind']}", prefer="quality")
        if not reply.ok or not reply.text.strip():
            break
        answer = safety.strip_code(reply.text.strip())
        state.answer_desk_question(row["id"], answer, reply.model)
        _side_effects(cfg, state, row, answer)
        answered += 1
    return answered


def sync(cfg: Config, state: State, timeout: int = 45) -> str:
    """Ingest the desk outbox; with a self-hosted desk, rsync it down first. Never raises."""
    d = cfg.section("desk")
    web = cfg.section("web")
    host = web.get("host") if web.get("enabled") else None
    if not d.get("enabled"):
        return "desk sync off"
    local = cfg.root / "desk" / "outbox"
    local.mkdir(parents=True, exist_ok=True)
    if not host:
        counts = ingest(cfg, state, local)
        total = sum(counts.values())
        return "desk: " + (
            ", ".join(f"{v} {k}" for k, v in counts.items() if v) if total else "nothing new"
        )
    remote = str(d.get("remote_data", "services/fenrir-boss/data")).rstrip("/") + "/outbox/"
    cmd = [
        "rsync",
        "-az",
        "-e",
        "ssh -o BatchMode=yes -o ConnectTimeout=10",
        f"{host}:{remote}",
        f"{local}/",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return f"desk sync failed: {type(exc).__name__}"
    if proc.returncode != 0:
        return f"desk sync failed: {(proc.stderr or '').strip()[:160]}"
    counts = ingest(cfg, state, local)
    total = sum(counts.values())
    if not total:
        return "desk sync: nothing new"
    return "desk sync: " + ", ".join(f"{v} {k}" for k, v in counts.items() if v)


def deploy(cfg: Config, timeout: int = 120) -> list[str]:
    """Self-hosting: copy the package and boss.toml to your server and restart the unit."""
    from boss.config import PACKAGE_DIR

    d = cfg.section("desk")
    host = cfg.section("web").get("host")
    if not host:
        return ["web.host missing in boss.toml"]
    app = str(d.get("remote_app", "services/fenrir-boss/app")).rstrip("/")
    ssh = "ssh -o BatchMode=yes -o ConnectTimeout=10"
    steps = [
        ["ssh", host, f"mkdir -p {app} {d.get('remote_data', 'services/fenrir-boss/data')}/outbox"],
        [
            "rsync",
            "-az",
            "--delete",
            "--exclude",
            "__pycache__",
            "-e",
            ssh,
            f"{PACKAGE_DIR}/",
            f"{host}:{app}/boss/",
        ],
        ["rsync", "-az", "-e", ssh, str(cfg.toml_path), f"{host}:{app}/boss.toml"],
        [
            "ssh",
            host,
            "systemctl --user restart fenrir-boss-desk.service && sleep 1 && "
            f"curl -s 127.0.0.1:{d.get('port', 8110)}/health",
        ],
    ]
    out: list[str] = []
    for cmd in steps:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            out.append(f"{cmd[0]}: {type(exc).__name__}")
            return out
        if proc.returncode != 0:
            out.append(f"{cmd[0]} failed: {(proc.stderr or proc.stdout).strip()[:200]}")
            return out
        out.append(f"{cmd[0]} ok {proc.stdout.strip()[:120]}")
    return out
