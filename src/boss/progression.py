"""When the learner moves up a level: enough accepted tickets, plus a passed gate 1:1."""

from __future__ import annotations

import json

from boss import corpus, ladder
from boss.config import Config
from boss.llm import extract_json
from boss.state import State


def gate_questions(cfg: Config, state: State, llm, level: int) -> list[str]:
    """Four gate questions for a level, written once from the study material and cached.
    Falls back to the static list in ladder.py when no model is available."""
    lvl = ladder.get_level(level)
    cached = state.get_meta(f"gate_qs:L{level}")
    if cached:
        try:
            qs = json.loads(cached)
            if isinstance(qs, list) and qs:
                return [str(q) for q in qs]
        except json.JSONDecodeError:
            pass
    if llm is None:
        return list(lvl.gate_questions)
    material = corpus.block(cfg, " ".join(lvl.competencies), k=6, chars=350)
    prompt = (
        f"Write four questions you ask {cfg.engineer_name} in a 1:1 to check they understand "
        f'level L{level} "{lvl.name}" ({lvl.phase}). Each answerable in one or two spoken '
        "sentences, each about a different competency, each grounded in the material below "
        "(you may name a source by its title when the material has one). No trick questions, "
        "no code to write. Return ONLY a "
        'JSON object: {"questions": ["...", "...", "...", "..."]}.\n\nCompetencies:\n'
        + "\n".join(f"- {c}" for c in lvl.competencies)
        + "\n\nMaterial:\n"
        + (material or "(none retrieved; use the competencies)")
    )
    from boss.persona import system_prompt

    reply = llm.quality(system_prompt(cfg, state), prompt, purpose=f"gate questions L{level}")
    if reply.ok:
        try:
            qs = [str(q) for q in extract_json(reply.text).get("questions", [])][:5]
        except (ValueError, AttributeError):
            qs = []
        if len(qs) >= 3:
            state.set_meta(f"gate_qs:L{level}", json.dumps(qs, ensure_ascii=False))
            return qs
    return list(lvl.gate_questions)


def gate_passed(state: State, level: int) -> bool:
    return state.get_meta(f"gate:L{level}") == "passed"


def eligible(state: State, level: int) -> tuple[bool, str]:
    lvl = ladder.get_level(level)
    n = state.accepted_count(level)
    if n < lvl.required_accepted:
        return False, f"{n}/{lvl.required_accepted} tickets accepted at L{level}"
    if level >= 1 and not gate_passed(state, level):
        return (
            False,
            f"{n}/{lvl.required_accepted} accepted; the gate 1:1 for L{level} is not passed yet",
        )
    return True, f"{n}/{lvl.required_accepted} accepted and gate passed"


def needs_gate_meeting(state: State, level: int) -> bool:
    lvl = ladder.get_level(level)
    return (
        level >= 1
        and state.accepted_count(level) >= lvl.required_accepted
        and not gate_passed(state, level)
    )


def maybe_level_up(state: State) -> str | None:
    level = state.level
    if ladder.is_top(level):
        return None
    ok, why = eligible(state, level)
    if not ok:
        return None
    state.set_level(level + 1, why)
    nxt = ladder.get_level(level + 1)
    return f"Level up. You are now L{level + 1} {nxt.name} ({nxt.phase})."
