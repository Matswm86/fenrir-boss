"""`boss track new` and `boss persona generate`: the model drafts, the validator decides.

A generated track is saved as JSON under <root>/tracks/ and is plain data: read it, edit it,
delete it. Nothing is activated until boss.toml names it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from boss import tracks
from boss.config import Config
from boss.llm import LLM, extract_json
from boss.persona import render

KEY_RE = re.compile(r"[^a-z0-9]+")


class GenerationError(RuntimeError):
    pass


def slug(text: str) -> str:
    return KEY_RE.sub("-", text.lower()).strip("-")[:40] or "custom"


def new_track(cfg: Config, llm: LLM, role: str, notes: str = "", key: str = "") -> Path:
    """Two attempts; the second one is told exactly why the first was rejected."""
    prompt = render(
        "track",
        role=role,
        notes=f"Notes from the learner about where they start and what they want: {notes}"
        if notes
        else "",
    )
    system = "You design vocational curricula. You answer with one JSON object and nothing else."
    user, problem = prompt, ""
    for attempt in (1, 2):
        reply = llm.quality(system, user, purpose=f"track draft attempt {attempt}", timeout=600)
        if not reply.ok:
            raise GenerationError(f"the model did not answer: {reply.error}")
        try:
            data = extract_json(reply.text)
            head = data.setdefault("track", {})
            head["key"] = key or slug(str(head.get("key") or role))
            head.setdefault("role", role)
            for i, level in enumerate(data.get("levels") or []):
                if isinstance(level, dict) and i > 0:
                    level.pop("seed", None)
            track = tracks.parse(data, source="generated")
        except (ValueError, tracks.TrackError) as exc:
            problem = str(exc)
            user = (
                f"{prompt}\n\nYour previous JSON was rejected: {problem}. "
                "Fix that and return the whole JSON again."
            )
            continue
        folder = cfg.root / "tracks"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{track.key}.json"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return path
    raise GenerationError(f"two drafts failed validation; the last problem: {problem}")


def new_bible(cfg: Config, llm: LLM, notes: str = "") -> Path:
    boss, company = cfg.section("boss"), cfg.section("company")
    prompt = render(
        "bible_gen",
        boss_name=cfg.boss_name,
        boss_title=boss.get("title", ""),
        boss_style=boss.get("style", "direct"),
        intensity=boss.get("intensity", "firm"),
        setting=cfg.setting,
        role=cfg.role,
        notes=f"Extra wishes from the person setting this up: {notes}" if notes else "",
    )
    # $company_name / $engineer_name stay literal: persona.py fills them on every render.
    reply = llm.quality(
        "You write character backstories for simulations. Plain prose, no headings.",
        prompt.replace("$company_city", str(company.get("city", "a mid-sized city"))),
        purpose="persona backstory",
    )
    if not reply.ok or len(reply.text.split()) < 120:
        raise GenerationError(f"no usable backstory: {reply.error or 'reply too short'}")
    path = cfg.root / "company" / "BIBLE.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(reply.text.strip().replace("—", ", ") + "\n", encoding="utf-8")
    return path
