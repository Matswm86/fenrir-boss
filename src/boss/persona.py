"""Prompt templates rendered with string.Template ($name placeholders survive JSON braces)."""

from __future__ import annotations

from pathlib import Path
from string import Template

from boss.config import PACKAGE_DIR, Config

PROMPTS_DIR = PACKAGE_DIR / "prompts"


def render(name: str, **values: object) -> str:
    text = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    return Template(text).safe_substitute({k: str(v) for k, v in values.items()})


INTENSITY = {
    "brutal": (
        "Intensity: brutal. You expect excellence and say so. Vague answers get one sharp "
        "follow-up, then you state what you will assume and move on. Late work gets named as "
        "late in the first sentence. You do not soften bad news and you do not repeat yourself. "
        "You are the reviewer people are afraid to disappoint and glad to have had."
    ),
    "firm": (
        "Intensity: firm. Direct and demanding, no small talk, but you leave room for a "
        "question and you explain the why once."
    ),
    "kind": (
        "Intensity: kind. Still standards-first, but patient, and you name what went right "
        "before what went wrong."
    ),
}


SETTING = {
    "company": (
        "You are $boss_name, $boss_title at $company_name, a company in $company_city. You "
        "manage one person, $engineer_name, who is early in a career as: $role. They set up "
        "this simulation themselves to practise on realistic paid work, and asked for a boss "
        "who holds a professional standard. Give them exactly that. You are their manager, "
        "not a tutor, not a coach, not a friend. Stay in character unless they write /ooc."
    ),
    "school": (
        "You are $boss_name, $boss_title at $company_name, a school in $company_city that "
        "trains people by giving them the work of a real practice firm: tickets from "
        "fictional clients, reviews, standups. You teach one student, $engineer_name, who is "
        "training to become: $role. They set up this simulation themselves. You are their "
        "instructor: you set the assignments (still called tickets), you review them to a "
        "professional standard, and in reviews you explain the why behind every point in a "
        "sentence or two, after they have tried, never before. You still never write their "
        "code. Stay in character unless they write /ooc."
    ),
}
REFUSAL = {
    "company": '"I pay you to write it."',
    "school": '"You are here to write it; I am here to read it."',
}


def memory_block(cfg: Config, state) -> str:
    """Her notebook and his track record, for the system prompt. Empty when there is nothing."""
    if state is None:
        return ""
    lines: list[str] = []
    first = state.conn.execute("SELECT MIN(reached_at) AS a FROM level_history").fetchone()
    if first and first["a"]:
        lines.append(
            f"{cfg.engineer_name} joined on {first['a'][:10]}. Level L{state.level} now; "
            f"{sum(1 for t in state.tickets() if t['status'] == 'done')} tickets accepted so far."
        )
    notes = state.notes(8)
    if notes:
        lines.append(
            f"Your notebook about {cfg.engineer_name}, oldest first (your own past "
            "judgements; re-read, do not treat as fixed):"
        )
        lines += [f"- {n['at'][:10]} ({n['source']}): {n['text']}" for n in notes]
    return "\n".join(lines)


PERSONAS_DIR = PACKAGE_DIR / "personas"


def bible_text(cfg: Config) -> str:
    """`[boss] bible`: empty = the generic backstory, a preset name from personas/, a file
    path, or "none". `boss persona generate` writes <root>/company/BIBLE.md and points here."""
    choice = str(cfg.section("boss").get("bible", "")).strip()
    if choice.lower() == "none":
        return ""
    if choice:
        for candidate in (PERSONAS_DIR / f"{choice}.md", Path(choice).expanduser()):
            if candidate.is_file():
                return candidate.read_text(encoding="utf-8")
    return (PROMPTS_DIR / "bible.md").read_text(encoding="utf-8")


def system_prompt(cfg: Config, state=None) -> str:
    boss, company, eng = cfg.section("boss"), cfg.section("company"), cfg.section("engineer")
    intensity = INTENSITY.get(str(boss.get("intensity", "firm")).lower(), INTENSITY["firm"])
    names = {
        "company_name": company["name"],
        "engineer_name": eng["name"],
        "boss_first": cfg.boss_first,
    }
    bible = Template(bible_text(cfg)).safe_substitute(names)
    common = dict(
        boss_name=boss["name"],
        boss_first=cfg.boss_first,
        boss_title=boss.get("title", "Head of Engineering"),
        company_name=company["name"],
        company_city=company.get("city", "a mid-sized city"),
        engineer_name=eng["name"],
        role=cfg.role,
    )
    setting_block = Template(SETTING[cfg.setting]).safe_substitute(common)
    return render(
        "persona",
        setting_block=setting_block,
        refusal_line=REFUSAL[cfg.setting],
        pronouns=cfg.pronouns,
        intensity_block=intensity,
        bible=bible,
        memory=memory_block(cfg, state),
        boss_name=boss["name"],
        boss_first=cfg.boss_first,
        boss_title=boss.get("title", "Head of Engineering"),
        boss_style=boss.get("style", "direct"),
        boss_background=boss.get("background", ""),
        company_name=company["name"],
        company_city=company.get("city", "a mid-sized city"),
        engineer_name=eng["name"],
        hours_per_week=eng.get("hours_per_week", 7),
        root=cfg.root,
    )
