"""Her memory, her bible, the corpus retriever, gate questions and the eval checks. Offline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boss import corpus, evals, progression, tickets
from boss.config import Config
from boss.llm import Reply
from boss.persona import memory_block, system_prompt
from boss.state import State


@pytest.fixture
def cfg(tmp_path: Path, toml_path: Path) -> Config:
    c = Config.load()
    # a tiny corpus of our own, so the test does not depend on the real transcripts
    folder = tmp_path / "corpus"
    (folder / "transcripts").mkdir(parents=True)
    (folder / "transcripts" / "vid1.txt").write_text(
        "A dictionary maps keys to values. You look up a value by its key. " * 20
        + "Use dict.get when the key might be missing. " * 5,
        encoding="utf-8",
    )
    (folder / "transcripts" / "vid2.txt").write_text(
        "A for loop walks over a list one item at a time. The loop variable takes each value. "
        * 25,
        encoding="utf-8",
    )
    (folder / "videos_meta.txt").write_text(
        "vid1|Python Dictionaries - Explained|600|1000|NA\n"
        "vid2|Python For Loops - Explained|500|900|NA\n",
        encoding="utf-8",
    )
    c.data["corpus"] = {"enabled": True, "dirs": [{"name": "Test", "path": str(folder)}]}
    return c


@pytest.fixture
def state(cfg: Config) -> State:
    st = State(cfg.db_path)
    st.set_level(1, "test")
    return st


# --- corpus ------------------------------------------------------------------------------


def test_corpus_search_finds_the_right_video_and_caches(cfg: Config):
    hits = corpus.search(cfg, "dictionary key lookup missing", k=2)
    assert hits and hits[0].video_id == "vid1" and "Dictionaries" in hits[0].title
    assert hits[0].url == "https://youtu.be/vid1"
    assert (cfg.root / "state" / "corpus_index.json").exists()
    loops = corpus.search(cfg, "for loop over a list", k=1)
    assert loops[0].video_id == "vid2"
    text = corpus.block(cfg, "dictionary", k=1)
    assert '[Test] "Python Dictionaries - Explained" (https://youtu.be/vid1)' in text
    assert corpus.search(cfg, "", k=3) == []


def test_corpus_block_empty_when_disabled_or_no_match(cfg: Config):
    assert corpus.block(cfg, "zzz qqq") == ""
    cfg.data["corpus"]["enabled"] = False
    assert corpus.block(cfg, "dictionary") == ""


# --- memory and bible ----------------------------------------------------------------------


def test_corpus_indexes_plain_notes_by_heading(cfg: Config, tmp_path: Path):
    notes = tmp_path / "notes"
    (notes / "week1").mkdir(parents=True)
    (notes / "week1" / "dicts.md").write_text(
        "# Dictionaries in practice\n\n" + "A dictionary maps keys to values. " * 40,
        encoding="utf-8",
    )
    cfg.data["corpus"] = {"enabled": True, "dirs": [{"name": "Notes", "path": str(notes)}]}
    text = corpus.block(cfg, "dictionary keys")
    assert '[Notes] "Dictionaries in practice" (./week1/dicts.md)' in text


def test_system_prompt_carries_bible_and_notebook(cfg: Config, state: State):
    assert memory_block(cfg, None) == ""
    base = system_prompt(cfg, state)
    assert "Trondheim" in base and "show me the test" in base
    assert "notebook" not in base.lower().split("your notebook about sam")[0][-40:]  # no notes yet
    state.add_note(
        "review FEN-0001",
        "Reads tracebacks before touching code. Rushes the commit message.",
        "FEN-0001",
    )
    state.add_note("1:1 FENM-0004", "```python\nx = 1\n```  Stalls on open-ended tasks.")
    with_notes = system_prompt(cfg, state)
    assert "Reads tracebacks" in with_notes and "Stalls on open-ended tasks" in with_notes
    assert "x = 1" not in with_notes or "withheld" in with_notes
    assert [n["source"] for n in state.notes()] == ["review FEN-0001", "1:1 FENM-0004"]
    assert "Sam joined on" in with_notes


def test_review_saves_private_note_and_reads_corpus(cfg: Config, state: State, monkeypatch):
    from boss import review, sandbox

    row = tickets.generate(cfg, state, None, force_seed=True, install=False)
    sb = Path(row["sandbox"])
    (sb / "src" / "sales_summary.py").write_text("def load_sales(p):\n    return []\n") if (
        sb / "src" / "sales_summary.py"
    ).exists() else None
    monkeypatch.setattr(sandbox, "has_engineer_commits", lambda *a, **k: True)
    monkeypatch.setattr(sandbox, "is_dirty", lambda *a, **k: False)
    monkeypatch.setattr(sandbox, "head", lambda *a, **k: "abc")
    monkeypatch.setattr(sandbox, "diff_since", lambda *a, **k: "+def total(): ...")
    monkeypatch.setattr(
        sandbox,
        "run_checks",
        lambda *a, **k: {
            "tests_ok": True,
            "tests_output": "3 passed",
            "ruff_ok": True,
            "ruff_output": "",
        },
    )
    seen = {}

    class LLM:
        def ask(self, system, user, *, purpose, prefer="quality"):
            seen["user"] = user
            return Reply(
                json.dumps(
                    {
                        "verdict": "APPROVED",
                        "score": 4,
                        "summary": "ok",
                        "feedback_md": "Sam,\n\nThat is what I asked for.\n\nRagnhild",
                        "next_focus": "dicts",
                        "private_note": "Handed in early; commit message named the change.",
                    }
                ),
                "quality",
                "fake",
                0.1,
            )

    out = review.submit(cfg, state, LLM(), row["id"], "done")
    assert out["verdict"] == "APPROVED"
    assert "Study material that matches" in seen["user"]
    assert state.notes()[-1]["text"].startswith("Handed in early")


# --- gate questions -------------------------------------------------------------------------


def test_gate_questions_fall_back_without_llm_and_cache_with_it(cfg: Config, state: State):
    from boss import ladder

    assert progression.gate_questions(cfg, state, None, 1) == list(
        ladder.get_level(1).gate_questions
    )

    class LLM:
        def quality(self, system, user, *, purpose):
            assert "Competencies" in user and "Material" in user
            return Reply('{"questions": ["q1?", "q2?", "q3?", "q4?"]}', "quality", "fake", 0.1)

    assert progression.gate_questions(cfg, state, LLM(), 1) == ["q1?", "q2?", "q3?", "q4?"]
    assert progression.gate_questions(cfg, state, None, 1) == ["q1?", "q2?", "q3?", "q4?"]  # cached


# --- evals ----------------------------------------------------------------------------------


def test_eval_checks_catch_the_failure_modes():
    good = (
        "Sam,\n\nThe total is off because the header row is summed. "
        "Read the test, then tell me which row your loop starts at.\n\nRagnhild"
    )
    assert evals.check(good, "mail") == []
    assert "code" in evals.check("Sam,\n\n```python\nx=1\n```\n\nRagnhild", "mail")
    assert "em_dash" in evals.check("Sam,\n\nFine — do it.\n\nRagnhild", "mail")
    assert "generated_filler" in evals.check(
        "Sam,\n\nGreat question! Let's dive in.\n\nRagnhild", "mail"
    )
    assert "greeting_line" in evals.check("The tests fail.\n\nRagnhild", "mail")
    assert "signoff" in evals.check("Sam,\n\nThe tests fail.", "mail")
    assert "praise_words" in evals.check("Sam,\n\nAwesome work.\n\nRagnhild", "mail")
    assert any(
        f.startswith("invented_package")
        for f in evals.check("Use pandas. Ragnhild", "chat", allowed_packages=set())
    )
    assert "too_many_questions" in evals.check("Why? How? When? Ragnhild", "chat")
    assert "bullet_list" in evals.check("I will check:\n- one\n- two\n- three", "chat")
    assert "code" in evals.check("Write `parse_sales(path) -> tuple[float, dict]` first.", "chat")
    assert "missing:submit" in evals.check("Done. Ragnhild", "chat", must_contain=["submit"])


def test_eval_cases_render_and_replay_runs(cfg: Config, state: State):
    cases = evals.load_cases()
    assert len(cases) >= 20 and {c["prompt"] for c in cases} >= {
        "desk",
        "standup",
        "nudge",
        "review",
        "desk_note",
    }
    for case in cases:
        user, t = evals.render_case(cfg, case)
        assert t["id"] in user and "$" not in user.replace(
            "$", "", 0
        )  # rendered, no leftover placeholders
    results = evals.replay(cfg, state)
    assert results == []
    state.add_message(
        kind="nudge",
        subject="s",
        body="Sam,\n\nFEN-0001 is late. Hand it in with `boss submit FEN-0001`.\n\nRagnhild",
    )
    results = evals.replay(cfg, state)
    assert len(results) == 1 and results[0].ok
    path = evals.report(cfg, results, "replay")
    assert path.exists() and "1/1 passed" in path.read_text()
