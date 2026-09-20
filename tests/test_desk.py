"""The desk, offline: bundle, queued handlers, ingest, answers by the tick, code stripping."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from boss import desk, meetings, publish, tickets
from boss.config import Config
from boss.llm import Reply
from boss.state import State


@pytest.fixture
def state(cfg: Config) -> State:
    st = State(cfg.db_path)
    st.set_level(0, "test")
    return st


@pytest.fixture
def seeded(cfg: Config, state: State) -> dict:
    return tickets.generate(cfg, state, None, force_seed=True, install=False)


class FakeLLM:
    """Answers every prompt with one canned text; records what it was asked."""

    def __init__(self, text="Read the traceback again. What did line 3 say? Ragnhild", ok=True):
        self.text, self.ok, self.calls = text, ok, []

    def ask(self, system, user, *, purpose, prefer="quality"):
        self.calls.append((system, user, purpose))
        return Reply(self.text, "quality", "fake", 0.1, ok=self.ok, error="" if self.ok else "down")

    quality = ask


def _desk(cfg: Config, state: State, tmp_path: Path) -> desk.Desk:
    site = publish.write_site(cfg, state)
    return desk.Desk(
        cfg,
        data_dir=tmp_path / "vps",
        bundle_path=site / "desk" / "bundle.json",
    )


def _synced(cfg: Config, d: desk.Desk) -> Path:
    """What sync() does with rsync: the VPS outbox lands under <root>/desk/outbox."""
    target = cfg.root / "desk" / "outbox"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(d.outbox, target)
    return target


# --- bundle ----------------------------------------------------------------------------


def test_bundle_carries_ticket_tests_and_folds_home(cfg: Config, state: State, seeded: dict):
    b = desk.bundle(cfg, state)
    assert b["open"] == [seeded["id"]]
    t = b["tickets"][0]
    assert t["test_files"] == ["test_hello.py"] and t["test_names"]
    assert t["acceptance"] and "/home/" not in json.dumps(b)
    assert b["needs_you"][0]["kind"] == "ticket"
    assert b["progress"]["tickets_done"] == 0
    assert b["answers"] == {} and b["pending"] == [] and "hour" in b["eta"]
    assert any(lv["current"] for lv in b["ladder"])


def test_write_site_emits_desk_files(cfg: Config, state: State, seeded: dict):
    site = publish.write_site(cfg, state)
    for name in ("index.html", "app.js", "desk.css", "bundle.json"):
        assert (site / "desk" / name).exists()
    assert "/desk/" in (site / "index.html").read_text()
    html = (site / "desk" / "index.html").read_text()
    assert '<script src="/desk/app.js">' in html and "onclick" not in html


# --- handlers: the VPS stores, it does not answer for her -------------------------------------


def test_ask_boss_is_queued_then_answered_by_the_tick(cfg, state, seeded, tmp_path):
    d = _desk(cfg, state, tmp_path)
    status, out = d.handle("POST", "/ask-boss", {"question": "What does criterion 2 mean?"})
    assert status == 200 and out["queued"] is True and out["who"] == "boss"
    assert out["eta"] == desk.ETA_TEXT
    status, act = d.handle("GET", "/activity", {})
    thread = act["threads"][seeded["id"]]
    assert thread[0]["pending"] is True and thread[0]["id"] == out["id"]
    # home: sync + answer
    assert desk.ingest(cfg, state, _synced(cfg, d))["queued"] == 1
    assert [r["id"] for r in state.pending_desk_questions()] == [out["id"]]
    llm = FakeLLM("Fine.\n```python\nprint(1)\n```\nNow run the tests. Ragnhild")
    assert desk.answer_pending(cfg, state, llm) == 1
    system, user, _ = llm.calls[0]
    assert seeded["id"] in user and "Acceptance criteria" in user
    assert "You do not write Sam's code" in system and "Trondheim" in system  # persona + bible
    answer = state.desk_answers()[out["id"]]
    assert "print(1)" not in answer["reply"] and "withheld" in answer["reply"]
    assert desk.bundle(cfg, state)["answers"][out["id"]]["reply"] == answer["reply"]
    thread_md = (cfg.root / "desk" / "threads" / f"{seeded['id']}.md").read_text()
    assert thread_md.count("withheld") == 1
    # the next prompt for her sees this exchange, and the second question carries it as history
    assert "criterion 2" in desk.thread_context(cfg, state, seeded["id"])
    d.handle("POST", "/ask-boss", {"question": "And criterion 3?"})
    desk.ingest(cfg, state, _synced(cfg, d))
    desk.answer_pending(cfg, state, llm)
    assert "What does criterion 2 mean?" in llm.calls[1][1]


def test_unanswerable_questions_stay_queued(cfg, state, seeded, tmp_path):
    d = _desk(cfg, state, tmp_path)
    d.handle("POST", "/ask-boss", {"question": "hi"})
    desk.ingest(cfg, state, _synced(cfg, d))
    assert desk.answer_pending(cfg, state, FakeLLM("", ok=False)) == 0
    assert len(state.pending_desk_questions()) == 1
    pending = [r["id"] for r in state.pending_desk_questions()]
    assert desk.bundle(cfg, state)["pending"] == pending


def test_strong_tutor_is_queued_and_answered_in_study_mode(cfg, state, seeded, tmp_path):
    d = _desk(cfg, state, tmp_path)
    status, out = d.handle("POST", "/ask-tutor", {"question": "What does AssertionError compare?"})
    assert status == 200 and out["queued"] and out["who"] == "tutor"
    act = d.handle("GET", "/activity", {})[1]
    assert act["threads"][seeded["id"]][0]["channel"] == "tutor"
    desk.ingest(cfg, state, _synced(cfg, d))
    llm = FakeLLM("Picture a bouncer. Type `print(1 == 2)` and tell me what you see.")
    assert desk.answer_pending(cfg, state, llm) == 1
    system, user, purpose = llm.calls[0]
    assert system == desk.tutor_system(cfg) and "never write" in user and seeded["id"] in user
    assert "Mimir" in (cfg.root / "desk" / "threads" / f"{seeded['id']}.md").read_text()
    assert "bouncer" in desk.thread_context(cfg, state, seeded["id"])


def test_tutor_context_names_ticket_and_forbids_code(cfg, state, seeded):
    t = desk.bundle(cfg, state)["tickets"][0]
    ctx = desk.tutor_context(t)
    assert seeded["id"] in ctx and "never write the code" in ctx and t["test_names"][0] in ctx


def test_bad_requests(cfg, state, seeded, tmp_path):
    d = _desk(cfg, state, tmp_path)
    assert d.handle("POST", "/ask-boss", {})[0] == 400
    assert d.handle("POST", "/standup", {"yesterday": "", "today": "", "blockers": ""})[0] == 400
    assert d.handle("POST", "/note", {"text": " "})[0] == 400
    assert d.handle("GET", "/nope", {})[0] == 404
    assert d.handle("GET", "/health", {})[1]["status"] == "ok"


# --- standups and notes: queued, answered, recorded ----------------------------------------


def test_standup_and_note_round_trip(cfg, state, seeded, tmp_path):
    d = _desk(cfg, state, tmp_path)
    d.handle("POST", "/standup", {"yesterday": "uv sync", "today": "tests", "blockers": "none"})
    d.handle("POST", "/note", {"text": "I need until Thursday."})
    counts = desk.ingest(cfg, state, _synced(cfg, d))
    assert counts["queued"] == 2 and counts["standup"] == 0
    assert desk.answer_pending(cfg, state, FakeLLM("Noted. Thursday it is. Ragnhild")) == 2
    held = [m for m in state.meetings() if m["type"] == "standup" and m["status"] == "held"]
    assert len(held) == 1 and "uv sync" in held[0]["transcript"]
    kinds = [m["kind"] for m in state.messages(10)]
    assert "standup" in kinds and "desk-note" in kinds
    inbox = (cfg.root / "INBOX.md").read_text()
    assert "Re: standup" in inbox and "Re: your note" in inbox
    assert (cfg.root / "company" / "DECISIONS.md").read_text().count("Thursday") == 2
    # idempotent on both sides
    assert desk.ingest(cfg, state, _synced(cfg, d))["queued"] == 0
    assert desk.answer_pending(cfg, state, FakeLLM()) == 0
    assert len([m for m in state.meetings() if m["type"] == "standup"]) == 1


def test_standup_answer_lands_on_that_days_meeting(cfg, state, seeded, tmp_path):
    sunday = datetime(2026, 9, 6, 20, 0, tzinfo=cfg.tz)
    meetings.plan_week(cfg, state, sunday.astimezone(UTC))
    standup = next(m for m in state.meetings() if m["type"] == "standup")
    at = datetime(2026, 9, 7, 10, 30, tzinfo=cfg.tz).astimezone(UTC).isoformat(timespec="seconds")
    outbox = tmp_path / "ob"
    desk.append_event(
        outbox,
        {"kind": "standup", "at": at, "answers": {"yesterday": "a", "today": "b", "blockers": ""}},
    )
    desk.ingest(cfg, state, outbox)
    desk.answer_pending(cfg, state, FakeLLM("Noted. Ragnhild"))
    assert state.get_meeting(standup["id"])["status"] == "held"


def test_read_events_skips_garbage(tmp_path: Path):
    ob = tmp_path / "ob"
    ob.mkdir()
    (ob / "2026-09-05.jsonl").write_text(
        '{"id": "a", "kind": "note", "at": "2026-09-05T10:00:00+00:00"}\nnot json\n{"kind": "x"}\n'
    )
    assert [e["id"] for e in desk.read_events(ob)] == ["a"]
