"""SQLite state: tickets, submissions, reviews, meetings, messages, events, llm calls."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS tickets (
    id TEXT PRIMARY KEY,
    seq INTEGER NOT NULL,
    level INTEGER NOT NULL,
    kind TEXT NOT NULL,                 -- code | doc
    title TEXT NOT NULL,
    slug TEXT NOT NULL,
    client TEXT NOT NULL,
    status TEXT NOT NULL,               -- open | changes_requested | done | cancelled
    created_at TEXT NOT NULL,
    due_at TEXT NOT NULL,
    sandbox TEXT NOT NULL,
    base_commit TEXT,
    brief TEXT NOT NULL,
    acceptance TEXT NOT NULL,           -- json list
    boss_notes TEXT NOT NULL,
    run_command TEXT,
    spec_json TEXT NOT NULL,
    source TEXT NOT NULL                -- llm | seed
);

CREATE TABLE IF NOT EXISTS submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id TEXT NOT NULL,
    submitted_at TEXT NOT NULL,
    message TEXT,
    head_commit TEXT,
    tests_ok INTEGER,                   -- 1 pass, 0 fail, NULL not applicable
    tests_output TEXT,
    ruff_output TEXT,
    diff_chars INTEGER
);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id INTEGER NOT NULL,
    ticket_id TEXT NOT NULL,
    verdict TEXT NOT NULL,
    score INTEGER,
    summary TEXT,
    feedback_md TEXT,
    next_focus TEXT,
    created_at TEXT NOT NULL,
    model TEXT
);

CREATE TABLE IF NOT EXISTS meetings (
    id TEXT PRIMARY KEY,
    seq INTEGER NOT NULL,
    type TEXT NOT NULL,                 -- standup | one_on_one | client_call
    when_at TEXT NOT NULL,              -- ISO, UTC
    status TEXT NOT NULL,               -- scheduled | notified | held | missed
    agenda TEXT NOT NULL,
    ticket_id TEXT,
    client TEXT,
    transcript TEXT,
    minutes TEXT,
    outcome_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    ticket_id TEXT,
    meeting_id TEXT,
    delivered_json TEXT
);

CREATE TABLE IF NOT EXISTS events (key TEXT PRIMARY KEY, at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    lane TEXT NOT NULL,
    model TEXT NOT NULL,
    purpose TEXT NOT NULL,
    seconds REAL,
    cost_usd REAL,
    ok INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS notebook (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    source TEXT NOT NULL,               -- review FEN-0007 | 1:1 FENM-0004 | admin
    ticket_id TEXT,
    text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS desk_questions (
    id TEXT PRIMARY KEY,                -- the desk event id
    at TEXT NOT NULL,
    kind TEXT NOT NULL,                 -- boss_question | standup | note
    ticket_id TEXT,
    payload_json TEXT NOT NULL,
    answer TEXT,
    answered_at TEXT,
    model TEXT
);

CREATE TABLE IF NOT EXISTS level_history (
    level INTEGER NOT NULL,
    reached_at TEXT NOT NULL,
    reason TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class State:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # --- meta ----------------------------------------------------------------
    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def next_seq(self, counter: str) -> int:
        current = int(self.get_meta(f"seq:{counter}", "0") or 0) + 1
        self.set_meta(f"seq:{counter}", str(current))
        return current

    # --- level -----------------------------------------------------------------
    @property
    def level(self) -> int:
        return int(self.get_meta("level", "0") or 0)

    def set_level(self, level: int, reason: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO level_history (level, reached_at, reason) VALUES (?, ?, ?)",
                (level, now_iso(), reason),
            )
        self.set_meta("level", str(level))

    # --- tickets -------------------------------------------------------------
    def insert_ticket(self, t: dict[str, Any]) -> None:
        cols = ",".join(t.keys())
        marks = ",".join("?" for _ in t)
        with self.conn:
            self.conn.execute(f"INSERT INTO tickets ({cols}) VALUES ({marks})", tuple(t.values()))

    def get_ticket(self, ticket_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()

    def tickets(self, status: str | None = None, level: int | None = None) -> list[sqlite3.Row]:
        sql, args = "SELECT * FROM tickets", []
        clauses = []
        if status:
            clauses.append("status = ?")
            args.append(status)
        if level is not None:
            clauses.append("level = ?")
            args.append(level)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        return self.conn.execute(sql + " ORDER BY seq", args).fetchall()

    def open_tickets(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM tickets WHERE status IN ('open','changes_requested') ORDER BY seq"
        ).fetchall()

    def update_ticket(self, ticket_id: str, **fields: Any) -> None:
        sets = ",".join(f"{k} = ?" for k in fields)
        with self.conn:
            self.conn.execute(
                f"UPDATE tickets SET {sets} WHERE id = ?", (*fields.values(), ticket_id)
            )

    def accepted_count(self, level: int) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM tickets WHERE level = ? AND status = 'done'", (level,)
        ).fetchone()
        return int(row["n"])

    def last_ticket_created(self) -> datetime | None:
        row = self.conn.execute("SELECT MAX(created_at) AS m FROM tickets").fetchone()
        return parse_iso(row["m"]) if row and row["m"] else None

    # --- submissions / reviews ----------------------------------------------
    def add_submission(self, **fields: Any) -> int:
        fields.setdefault("submitted_at", now_iso())
        cols = ",".join(fields.keys())
        marks = ",".join("?" for _ in fields)
        with self.conn:
            cur = self.conn.execute(
                f"INSERT INTO submissions ({cols}) VALUES ({marks})", tuple(fields.values())
            )
        return int(cur.lastrowid)

    def add_review(self, **fields: Any) -> int:
        fields.setdefault("created_at", now_iso())
        cols = ",".join(fields.keys())
        marks = ",".join("?" for _ in fields)
        with self.conn:
            cur = self.conn.execute(
                f"INSERT INTO reviews ({cols}) VALUES ({marks})", tuple(fields.values())
            )
        return int(cur.lastrowid)

    def recent_reviews(self, limit: int = 5) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT r.*, t.title FROM reviews r JOIN tickets t ON t.id = r.ticket_id "
            "ORDER BY r.id DESC LIMIT ?",
            (limit,),
        ).fetchall()

    # --- meetings ------------------------------------------------------------
    def insert_meeting(self, m: dict[str, Any]) -> None:
        m.setdefault("created_at", now_iso())
        cols = ",".join(m.keys())
        marks = ",".join("?" for _ in m)
        with self.conn:
            self.conn.execute(f"INSERT INTO meetings ({cols}) VALUES ({marks})", tuple(m.values()))

    def get_meeting(self, meeting_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)).fetchone()

    def meetings(self, status: str | None = None) -> list[sqlite3.Row]:
        if status:
            return self.conn.execute(
                "SELECT * FROM meetings WHERE status = ? ORDER BY when_at", (status,)
            ).fetchall()
        return self.conn.execute("SELECT * FROM meetings ORDER BY when_at").fetchall()

    def meeting_exists(self, mtype: str, when_iso: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM meetings WHERE type = ? AND when_at = ?", (mtype, when_iso)
        ).fetchone()
        return row is not None

    def update_meeting(self, meeting_id: str, **fields: Any) -> None:
        sets = ",".join(f"{k} = ?" for k in fields)
        with self.conn:
            self.conn.execute(
                f"UPDATE meetings SET {sets} WHERE id = ?", (*fields.values(), meeting_id)
            )

    # --- messages / events / llm ---------------------------------------------
    def add_message(self, **fields: Any) -> int:
        fields.setdefault("created_at", now_iso())
        cols = ",".join(fields.keys())
        marks = ",".join("?" for _ in fields)
        with self.conn:
            cur = self.conn.execute(
                f"INSERT INTO messages ({cols}) VALUES ({marks})", tuple(fields.values())
            )
        return int(cur.lastrowid)

    def set_delivery(self, message_id: int, delivered: dict[str, Any]) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE messages SET delivered_json = ? WHERE id = ?",
                (json.dumps(delivered), message_id),
            )

    def messages(self, limit: int = 10) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM messages ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()

    def once(self, key: str) -> bool:
        """True the first time a key is seen, False afterwards. Idempotency for the tick."""
        try:
            with self.conn:
                self.conn.execute("INSERT INTO events (key, at) VALUES (?, ?)", (key, now_iso()))
        except sqlite3.IntegrityError:
            return False
        return True

    def log_llm(self, **fields: Any) -> None:
        fields.setdefault("at", now_iso())
        cols = ",".join(fields.keys())
        marks = ",".join("?" for _ in fields)
        with self.conn:
            self.conn.execute(
                f"INSERT INTO llm_calls ({cols}) VALUES ({marks})", tuple(fields.values())
            )

    # --- the boss's notebook: private judgements about the learner -------------
    def add_note(self, source: str, text: str, ticket_id: str | None = None) -> None:
        from boss.safety import strip_code

        text = " ".join(strip_code(str(text)).split())
        if not text:
            return
        with self.conn:
            self.conn.execute(
                "INSERT INTO notebook (at, source, ticket_id, text) VALUES (?, ?, ?, ?)",
                (now_iso(), source, ticket_id, text[:600]),
            )

    def notes(self, limit: int = 8) -> list[sqlite3.Row]:
        rows = self.conn.execute(
            "SELECT * FROM notebook ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return list(reversed(rows))

    # --- desk questions waiting for her, answered by the tick -------------------
    def add_desk_question(self, event: dict[str, Any]) -> bool:
        payload = {k: v for k, v in event.items() if k not in {"id", "at", "kind", "ticket"}}
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO desk_questions (id, at, kind, ticket_id, payload_json) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        event["id"],
                        event.get("at") or now_iso(),
                        event["kind"],
                        event.get("ticket"),
                        json.dumps(payload, ensure_ascii=False),
                    ),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def pending_desk_questions(self, limit: int = 5) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM desk_questions WHERE answer IS NULL ORDER BY at LIMIT ?", (limit,)
        ).fetchall()

    def answer_desk_question(self, qid: str, answer: str, model: str) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE desk_questions SET answer = ?, answered_at = ?, model = ? WHERE id = ?",
                (answer, now_iso(), model, qid),
            )

    def answered_desk_questions(self, limit: int = 50) -> list[sqlite3.Row]:
        rows = self.conn.execute(
            "SELECT * FROM desk_questions WHERE answer IS NOT NULL ORDER BY answered_at DESC "
            "LIMIT ?",
            (limit,),
        ).fetchall()
        return list(reversed(rows))

    def desk_answers(self) -> dict[str, dict[str, Any]]:
        return {
            r["id"]: {"reply": r["answer"], "at": r["answered_at"], "model": r["model"]}
            for r in self.conn.execute(
                "SELECT id, answer, answered_at, model FROM desk_questions WHERE answer IS NOT NULL"
            ).fetchall()
        }

    def quality_calls_today(self) -> int:
        today = datetime.now(UTC).date().isoformat()
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM llm_calls WHERE lane = 'quality' AND at LIKE ?",
            (f"{today}%",),
        ).fetchone()
        return int(row["n"])

    def pushes_today(self, tz) -> int:
        """Messages since local midnight that left the inbox (email or phone push succeeded)."""
        start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM messages WHERE created_at >= ? AND "
            '(delivered_json LIKE \'%"email": "ok%\' OR delivered_json LIKE \'%"ntfy": "ok%\')',
            (start.astimezone(UTC).isoformat(timespec="seconds"),),
        ).fetchone()
        return int(row["n"])

    def spend_today(self) -> float:
        today = datetime.now(UTC).date().isoformat()
        row = self.conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) AS c FROM llm_calls WHERE at LIKE ?", (f"{today}%",)
        ).fetchone()
        return float(row["c"])
