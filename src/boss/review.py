"""Submission review: run the checks, ask the boss, enforce the facts, record the verdict."""

from __future__ import annotations

import json
from pathlib import Path

from boss import corpus, progression, projects, sandbox
from boss.config import Config
from boss.llm import LLM, Reply, extract_json
from boss.persona import render, system_prompt
from boss.safety import ensure_inside, strip_code
from boss.state import State

APPROVED, CHANGES = "APPROVED", "CHANGES_REQUESTED"


class SubmitError(RuntimeError):
    pass


def _status(flag: bool | None) -> str:
    return {True: "PASS", False: "FAIL", None: "not applicable"}[flag]


def _fallback(checks: dict, kind: str) -> dict:
    tests = checks["tests_ok"]
    verdict = APPROVED if (tests is True and kind == "code") else CHANGES
    return {
        "verdict": verdict,
        "score": 3 if verdict == APPROVED else 2,
        "summary": "Reviewed by the automated checks only; my reviewer was offline.",
        "feedback_md": (
            "I could not read your diff today, my reviewer is offline. The automated checks "
            f"say: tests {_status(tests)}, ruff {_status(checks['ruff_ok'])}. "
            + (
                "That is enough for this ticket, approved on the checks alone."
                if verdict == APPROVED
                else "Resubmit later with `boss submit`; nothing you committed is lost."
            )
        ),
        "next_focus": "",
    }


def submit(cfg: Config, state: State, llm: LLM | None, ticket_id: str, message: str) -> dict:
    t = state.get_ticket(ticket_id)
    if t is None:
        raise SubmitError(f"unknown ticket {ticket_id}")
    if t["status"] not in {"open", "changes_requested"}:
        raise SubmitError(f"{ticket_id} is {t['status']}; nothing to submit")
    path = ensure_inside(cfg.root, Path(t["sandbox"]))
    if not path.exists():
        raise SubmitError(f"sandbox missing: {path}")
    if not sandbox.has_engineer_commits(path, t["base_commit"]):
        raise SubmitError(
            "no commits after the skeleton. Commit your work first: git add -A && git commit"
        )
    dirty = sandbox.is_dirty(path)
    checks = sandbox.run_checks(path, t["run_command"])
    diff = sandbox.diff_since(path, t["base_commit"])
    submission_id = state.add_submission(
        ticket_id=ticket_id,
        message=message,
        head_commit=sandbox.head(path),
        tests_ok=None if checks["tests_ok"] is None else int(checks["tests_ok"]),
        tests_output=checks["tests_output"],
        ruff_output=checks["ruff_output"],
        diff_chars=len(diff),
    )
    spec = json.loads(t["spec_json"])
    prompt = render(
        "review",
        engineer_name=cfg.engineer_name,
        ticket_id=ticket_id,
        title=t["title"],
        client=t["client"],
        brief=t["brief"],
        acceptance="\n".join(f"- {a}" for a in json.loads(t["acceptance"])),
        boss_notes=t["boss_notes"],
        message=message or "(no message)",
        tests_status=_status(checks["tests_ok"]),
        tests_output=checks["tests_output"][-3000:],
        ruff_status=_status(checks["ruff_ok"]),
        ruff_output=checks["ruff_output"][-1500:],
        diff=diff,
        standards=render("standards", company_name=cfg.company),
        corpus_block=corpus.block(cfg, " ".join(spec.get("learning_goals", [])) or t["title"], k=3)
        or "(nothing retrieved)",
    )
    reply = (
        llm.ask(system_prompt(cfg, state), prompt, purpose=f"review {ticket_id}")
        if llm
        else Reply("", "none", "none", 0, ok=False)
    )
    parsed: dict | None = None
    if reply.ok:
        try:
            parsed = extract_json(reply.text)
        except ValueError:
            parsed = None
    model = reply.model if parsed else "fallback"
    if parsed is None:
        parsed = _fallback(checks, t["kind"])
    verdict = APPROVED if parsed.get("verdict") == APPROVED else CHANGES
    notes: list[str] = []
    if t["kind"] == "code" and checks["tests_ok"] is not True:
        if verdict == APPROVED:
            notes.append(
                "Overridden to CHANGES_REQUESTED: the tests do not pass, and tests are facts."
            )
        verdict = CHANGES
    feedback = str(parsed.get("feedback_md") or "").strip()
    if not cfg.reviews_may_contain_code:
        feedback = strip_code(feedback)
    if dirty:
        notes.append("Your working tree has uncommitted changes. I reviewed what you committed.")
    if notes:
        feedback += "\n\n" + "\n".join(f"Note: {n}" for n in notes)
    try:
        score = max(1, min(int(parsed.get("score") or 0), 5))
    except (TypeError, ValueError):
        score = 1
    state.add_review(
        submission_id=submission_id,
        ticket_id=ticket_id,
        verdict=verdict,
        score=score,
        summary=str(parsed.get("summary") or ""),
        feedback_md=feedback,
        next_focus=str(parsed.get("next_focus") or ""),
        model=model,
    )
    note = parsed.get("private_note")
    if note and str(note).strip().lower() not in {"null", "none", ""}:
        state.add_note(f"review {ticket_id}", strip_code(str(note)), ticket_id)
    state.update_ticket(ticket_id, status="done" if verdict == APPROVED else "changes_requested")
    level_up = None
    if verdict == APPROVED:
        series = spec.get("series")
        if series:
            projects.mark_milestone_done(state, series["key"], int(series["index"]))
        level_up = progression.maybe_level_up(state)
    n = state.conn.execute(
        "SELECT COUNT(*) AS n FROM reviews WHERE ticket_id = ?", (ticket_id,)
    ).fetchone()["n"]
    review_path = cfg.root / "reviews" / f"{ticket_id}-review-{n}.md"
    review_path.parent.mkdir(parents=True, exist_ok=True)
    body = (
        f"# Review {n} of {ticket_id}: {t['title']}\n\n"
        f"Verdict: {verdict}  \nScore: {score}/5  \nReviewer model: {model}\n\n"
        f"{parsed.get('summary', '')}\n\n{feedback}\n\n"
        f"## Automated checks\n\n- tests: {_status(checks['tests_ok'])}\n"
        f"- ruff: {_status(checks['ruff_ok'])}\n"
    )
    if parsed.get("next_focus"):
        body += f"\nNext focus: {parsed['next_focus']}\n"
    if level_up:
        body += f"\n{level_up}\n"
    review_path.write_text(body, encoding="utf-8")
    return {
        "verdict": verdict,
        "score": score,
        "summary": parsed.get("summary", ""),
        "feedback_md": feedback,
        "next_focus": parsed.get("next_focus", ""),
        "review_path": review_path,
        "checks": checks,
        "level_up": level_up,
        "model": model,
        "body": body,
    }
