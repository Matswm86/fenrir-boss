"""Unit tests for the boss package. No LLM calls: everything here runs offline."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from boss import ladder, progression, sandbox, seeds, tickets, tracks
from boss.config import Config
from boss.llm import extract_json
from boss.safety import SandboxError, ensure_inside, safe_relpath, strip_code
from boss.state import State
from boss.tick import in_quiet_hours, tick


@pytest.fixture
def state(cfg: Config) -> State:
    st = State(cfg.db_path)
    st.set_level(0, "test")
    return st


# --- pure helpers -------------------------------------------------------------------


def test_extract_json_handles_fences_and_prose():
    text = 'Here you go:\n```json\n{"a": 1, "b": {"c": "x}y"}}\n```\nthanks'
    assert extract_json(text) == {"a": 1, "b": {"c": "x}y"}}


def test_extract_json_rejects_garbage():
    with pytest.raises(ValueError):
        extract_json("no object here")


def test_strip_code_removes_fences_and_statements():
    text = "Look:\n```python\nprint(1)\n```\nand also\ndef f():\nplain sentence stays."
    out = strip_code(text)
    assert "print(1)" not in out
    assert "def f()" not in out
    assert "plain sentence stays." in out
    inline = "Write `parse_sales(path: pathlib.Path) -> tuple[float, dict]` and `dict.get` is fine."
    out = strip_code(inline)
    assert "parse_sales" not in out and "`dict.get`" in out
    assert "int(row" not in strip_code("compute `int(row['qty']) * float(row['unit_price'])` now")
    # two short spans in one sentence: the prose between them is not a span (live bug 2026-09-05)
    prose = "and `uv run pytest -q` goes green. The `.env` is a separate step, `git status` too."
    assert strip_code(prose) == prose


def test_safe_relpath_blocks_escapes():
    assert safe_relpath("src/x.py") == "src/x.py"
    for bad in ("../x", "/etc/passwd", ".git/config", ""):
        with pytest.raises(SandboxError):
            safe_relpath(bad)


def test_ensure_inside(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    assert ensure_inside(root, root / "a") == (root / "a").resolve()
    with pytest.raises(SandboxError):
        ensure_inside(root, tmp_path / "elsewhere")


def test_stub_violations_detect_logic():
    ok = 'def f(x):\n    """doc"""\n    raise NotImplementedError\n'
    bad = "def f(x):\n    return x + 1\n"
    assert tickets.stub_violations(ok, "src/a.py") == []
    assert tickets.stub_violations(bad, "src/a.py")


def test_progress_hints_counts_checkboxes(tmp_path: Path):
    md = tmp_path / "PROGRESS.md"
    md.write_text("## Phase 0\n- [x] a\n- [ ] b\n## Phase 1\n- [ ] c\n", encoding="utf-8")
    hints = ladder.progress_hints(md)
    assert "Phase 0: 1/2 ticked" in hints and "Phase 1: 0/1 ticked" in hints


def test_quiet_hours(cfg: Config):
    assert in_quiet_hours(datetime(2026, 9, 5, 23, 30, tzinfo=cfg.tz), cfg)
    assert in_quiet_hours(datetime(2026, 9, 5, 3, 0, tzinfo=cfg.tz), cfg)
    assert not in_quiet_hours(datetime(2026, 9, 5, 12, 0, tzinfo=cfg.tz), cfg)


# --- seeds and validation -------------------------------------------------------------


def test_seeds_validate_at_their_levels(cfg: Config):
    for key in tracks.available():
        tracks.activate(key)
        seeded = [lv for lv in ladder.LEVELS if lv.seed]
        assert seeded and seeded[0].number == 0
        for lv in seeded:
            spec = seeds.seed(cfg, lv, "FEN-0001")
            assert spec is not None and "$" not in json.dumps(spec["files"])
            tickets.validate_spec(spec, lv)
    tracks.activate("ai-engineer")


def test_validate_rejects_code_in_brief_and_logic_in_stub(cfg: Config):
    spec = seeds.seed(cfg, ladder.get_level(1), "FEN-0001")
    spec["brief"] = "do this ```python\nx=1\n```"
    with pytest.raises(tickets.TicketError):
        tickets.validate_spec(spec, ladder.get_level(1))
    spec = seeds.seed(cfg, ladder.get_level(1), "FEN-0001")
    spec["files"]["src/sales_summary.py"] = "def load_sales(p):\n    return []\n"
    with pytest.raises(tickets.TicketError):
        tickets.validate_spec(spec, ladder.get_level(1))


def test_validate_drops_unlisted_dependencies(cfg: Config):
    spec = seeds.seed(cfg, ladder.get_level(1), "FEN-0001")
    spec["dependencies"] = ["requests", "evil-typosquat"]
    out = tickets.validate_spec(spec, ladder.get_level(1))
    assert out["dependencies"] == []  # requests is not allowed at L1
    assert len(out["warnings"]) == 2


# --- state ----------------------------------------------------------------------------


def test_once_is_idempotent(state: State):
    assert state.once("k")
    assert not state.once("k")


def test_progression_requires_gate_from_l1(state: State):
    assert progression.eligible(state, 0) == (False, "0/1 tickets accepted at L0")
    state.set_level(1, "t")
    for i in range(6):
        state.insert_ticket(
            {
                "id": f"FEN-{i:04d}",
                "seq": i,
                "level": 1,
                "kind": "code",
                "title": "t",
                "slug": "s",
                "client": "c",
                "status": "done",
                "created_at": "2026-09-01T00:00:00+00:00",
                "due_at": "2026-09-02T00:00:00+00:00",
                "sandbox": "/tmp/x",
                "brief": "b",
                "acceptance": "[]",
                "boss_notes": "n",
                "spec_json": "{}",
                "source": "seed",
            }
        )
    ok, why = progression.eligible(state, 1)
    assert not ok and "gate" in why
    state.set_meta("gate:L1", "passed")
    assert progression.maybe_level_up(state) is not None
    assert state.level == 2


# --- sandbox and tick, offline ------------------------------------------------------------


def test_seed_ticket_creates_sandbox_and_fails_on_stub(cfg: Config, state: State):
    row = tickets.generate(cfg, state, None, force_seed=True, install=False)
    path = Path(row["sandbox"])
    assert row["id"] == "FEN-0001" and path.is_dir()
    assert (path / "TICKET.md").exists() and (path / "tests" / "test_hello.py").exists()
    assert (path / ".gitignore").read_text().startswith(".venv/")
    assert sandbox.head(path) == row["base_commit"]
    assert not sandbox.has_engineer_commits(path, row["base_commit"])
    checks = sandbox.run_checks(path, "uv run pytest -q")
    assert checks["tests_ok"] is False


def test_tick_offline_assigns_seed_and_plans_meetings(cfg: Config, state: State):
    noon = datetime(2026, 9, 7, 10, 0, tzinfo=cfg.tz).astimezone(UTC)  # a Monday
    actions = tick(cfg, state, None, now=noon, force=True)
    assert any(a.startswith("assigned FEN-0001") for a in actions)
    kinds = {m["type"] for m in state.meetings()}
    assert {"standup", "one_on_one"} <= kinds
    assert (cfg.root / "INBOX.md").exists()
    assert list(cfg.calendar_dir.glob("*.ics"))
    # second tick: nothing new, gap not passed, no duplicate meetings
    n_meetings = len(state.meetings())
    actions2 = tick(cfg, state, None, now=noon, force=False)
    assert len(state.meetings()) == n_meetings
    assert not any(a.startswith("assigned") for a in actions2)


def test_tick_respects_quiet_hours(cfg: Config, state: State):
    night = datetime(2026, 9, 7, 23, 30, tzinfo=cfg.tz).astimezone(UTC)
    assert tick(cfg, state, None, now=night)[0].startswith("quiet hours")
    assert state.tickets() == []


def test_spec_json_roundtrip(cfg: Config, state: State):
    row = tickets.generate(cfg, state, None, force_seed=True, install=False)
    spec = json.loads(state.get_ticket(row["id"])["spec_json"])
    assert spec["title"] == row["title"]


# --- model lanes ----------------------------------------------------------------------


def test_quality_lane_falls_back_to_second_model(cfg: Config, state: State, monkeypatch):
    import subprocess
    from types import SimpleNamespace

    from boss import llm as llm_mod

    cfg.data["llm"]["quality"].update({"model": "fable", "fallback_model": "sonnet"})
    seen = []

    def fake_run(cmd, **kw):
        model = cmd[cmd.index("--model") + 1]
        seen.append(model)
        if model == "fable":
            return SimpleNamespace(
                returncode=1, stdout='{"is_error": true, "result": "overloaded"}', stderr=""
            )
        return SimpleNamespace(
            returncode=0, stdout='{"result": "OK from sonnet", "total_cost_usd": 0.01}', stderr=""
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    reply = llm_mod.LLM(cfg, state).quality("sys", "user", purpose="t")
    assert reply.ok and reply.model == "sonnet" and seen == ["fable", "sonnet"]
    assert state.quality_calls_today() == 2


# --- volume rules --------------------------------------------------------------------


def test_pushes_capped_weekday_only_and_only_for_push_kinds(cfg: Config, state: State, monkeypatch):
    from boss import channels

    cfg.data["channels"].update({"email": True, "ntfy": True, "desktop": False})
    monkeypatch.setattr(channels, "_email", lambda *a, **k: "ok via test to x@y")
    monkeypatch.setattr(channels, "_ntfy", lambda *a, **k: "ok")
    monday = datetime(2026, 9, 7, 10, 0, tzinfo=cfg.tz)
    monkeypatch.setattr(channels, "_now_local", lambda c: monday)
    monkeypatch.setattr(state, "pushes_today", lambda tz: state._pushes)  # count via delivery
    state._pushes = 0

    def send(kind, **kw):
        r = channels.deliver(cfg, state, kind=kind, subject="s", body="b", **kw)
        if r.get("email", "").startswith("ok"):
            state._pushes += 1
        return r

    assert "email" not in send("invite")  # invites never leave the inbox
    assert "held" in send("invite")["push"]
    assert send("ticket")["email"].startswith("ok")
    assert send("review")["ntfy"] == "ok"
    third = send("nudge")
    assert "email" not in third and third["push"] == "held: daily cap of 2 pushes reached"
    assert send("test", force=True)["email"].startswith("ok")  # explicit test skips the cap
    saturday = datetime(2026, 9, 5, 12, 0, tzinfo=cfg.tz)
    monkeypatch.setattr(channels, "_now_local", lambda c: saturday)
    state._pushes = 0
    assert send("ticket")["push"] == "held: weekend"
    assert len(state.messages(20)) == 7  # every message is still in the inbox


def test_pushes_today_counts_only_successful_pushes(cfg: Config, state: State):
    import json as _json

    for delivered in (
        {"email": "ok via primary to x"},
        {"ntfy": "ok"},
        {"push": "held: weekend"},
        {"email": "failed: x", "ntfy": "error: y"},
    ):
        mid = state.add_message(kind="ticket", subject="s", body="b")
        state.set_delivery(mid, delivered)
    assert state.pushes_today(cfg.tz) == 2
    assert _json.loads(state.messages(1)[0]["delivered_json"])["email"].startswith("failed")


# --- tracks, settings, providers ------------------------------------------------------


def test_every_builtin_track_parses_and_starts_with_onboarding():
    found = tracks.available()
    assert {"python-foundations", "ai-engineer", "software-engineer"} <= set(found)
    for path in found.values():
        t = tracks.load_file(path)
        assert t.levels[0].seed == "onboarding" and len(t.levels) >= 6 and len(t.clients) >= 5
    tracks.activate("ai-engineer")


def test_track_parse_names_the_broken_field():
    with pytest.raises(tracks.TrackError, match="levels"):
        tracks.parse({"track": {"key": "x", "name": "X"}, "levels": []})
    with pytest.raises(tracks.TrackError, match="competencies"):
        tracks.parse(
            {
                "track": {"key": "x", "name": "X"},
                "levels": [{"name": "a"}, {"name": "b"}],
            }
        )


def test_wizard_writes_loadable_settings_for_both_settings(tmp_path: Path, monkeypatch):
    import argparse

    from boss import wizard
    from boss.persona import system_prompt

    for setting, needle in (("company", "You manage one person"), ("school", "You teach one")):
        target = tmp_path / f"{setting}.toml"
        args = argparse.Namespace(
            config=str(target), yes=True, force=False, setting=setting, company='Acme "Labs"',
            city=None, boss="Dana Okoye", title=None, intensity=None, tutor=None, name="Kim",
            pronouns="she/her", timezone="UTC", hours="5", root=str(tmp_path / setting),
            track="software-engineer", role="platform engineer", provider="none",
            base_url=None, quality_model=None, cheap_model=None,
        )  # fmt: skip
        assert wizard.run(args) == 0
        monkeypatch.setenv("BOSS_TOML", str(target))
        loaded = Config.load()
        assert loaded.company == "Acme Labs" and loaded.ticket_prefix == "ACM"
        assert loaded.setting == setting and loaded.role == "platform engineer"
        prompt = system_prompt(loaded)
        assert needle in prompt and "Dana Okoye" in prompt and "she/her" in prompt
        assert "$" not in prompt.replace("$root", "")
    tracks.activate("ai-engineer")


def test_openai_compatible_lane_keeps_a_meeting_session(cfg: Config, state: State, monkeypatch):
    import io
    import urllib.request

    from boss import llm as llm_mod

    cfg.data["llm"]["quality"] = {
        "provider": "openai-compatible",
        "base_url": "http://localhost:11434/v1",
        "model": "local-model",
    }
    bodies = []

    def fake_urlopen(req, timeout=0):
        bodies.append(json.loads(req.data))
        text = f"reply {len(bodies)}"
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": text}}]}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    llm = llm_mod.LLM(cfg, state)
    first = llm.quality("sys", "open", purpose="t", persist=True)
    second = llm.quality("sys", "next", purpose="t", session_id=first.session_id, persist=True)
    assert first.ok and second.ok and second.text == "reply 2"
    assert [m["role"] for m in bodies[1]["messages"]] == ["system", "user", "assistant", "user"]
