"""Evals for the boss's prompts: does the character stay in voice, code-free and consistent?

Two modes. `run` renders a prompt with a fixture case, calls a model lane, and applies the
deterministic checks below. `replay` applies the same checks to what was already produced
(reviews, standup replies, desk answers, nudges) without any model call. `--judge` adds one
quality-lane call per output for the things a regex cannot see: self-contradiction, invented facts,
a voice that reads generated. Results land in <root>/evals/<date>.md.
"""

from __future__ import annotations

import contextlib
import json
import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

from boss import desk, ladder, safety, seeds
from boss.config import PACKAGE_DIR, Config
from boss.llm import LLM, extract_json
from boss.persona import render, system_prompt
from boss.state import State

CASES_PATH = PACKAGE_DIR / "evals" / "cases.json"
FILLER_RE = re.compile(
    r"\b(I hope this (finds|helps)|as an AI|great question|let'?s dive|in summary|feel free to|"
    r"certainly!|absolutely!|I'?m here to help|happy to help|as requested|please note that|"
    r"it'?s worth noting|in today'?s|game.changer|delve)\b",
    re.I,
)
HEADING_RE = re.compile(r"^\s*(#{1,6} |\*\*[^*]+\*\*\s*$)", re.M)
BULLET_RE = re.compile(r"^\s*[-*] ", re.M)
SENTENCE_RE = re.compile(r"[.!?](\s|$)")
PRAISE_RE = re.compile(r"\b(great|awesome|super|amazing|fantastic|excellent)\b", re.I)
PACKAGE_RE = re.compile(
    r"\b(requests|httpx|pandas|numpy|fastapi|flask|django|pydantic|sqlalchemy|langchain|"
    r"llama.index|openai|anthropic|beautifulsoup4?|bs4|scrapy|aiohttp|typer|click|rich)\b",
    re.I,
)
MAIL_KINDS = {"mail", "review", "nudge", "ticket"}


@dataclass
class Result:
    case_id: str
    prompt: str
    kind: str
    output: str
    failures: list[str] = field(default_factory=list)
    skipped: str = ""
    judge: dict | None = None

    @property
    def ok(self) -> bool:
        return not self.failures and not self.skipped and not (self.judge or {}).get("fail")


# --- deterministic checks --------------------------------------------------------------------


def check(
    text: str,
    kind: str,
    *,
    allowed_packages: set[str] | None = None,
    max_sentences: int = 8,
    engineer: str = "Sam",
    boss_first: str = "Ragnhild",
    must_contain: list[str] | None = None,
    must_not_contain: list[str] | None = None,
) -> list[str]:
    """Names of failed checks. Empty list = passes."""
    fails: list[str] = []
    stripped = safety.strip_code(text)
    if stripped != text:
        fails.append("code")
    if "—" in text or "–" in text:
        fails.append("em_dash")
    if FILLER_RE.search(text):
        fails.append("generated_filler")
    if PRAISE_RE.search(text):
        fails.append("praise_words")
    if HEADING_RE.search(text):
        fails.append("headings")
    if kind in MAIL_KINDS:
        first = text.strip().splitlines()[0].strip() if text.strip() else ""
        if not first.startswith(f"{engineer},") and not first.startswith(f"{engineer}."):
            fails.append("greeting_line")
    if len(BULLET_RE.findall(text)) > (3 if kind in MAIL_KINDS else 1):
        fails.append("bullet_list")
    if kind in MAIL_KINDS and not text.rstrip().endswith(boss_first):
        fails.append("signoff")
    n_sent = len(SENTENCE_RE.findall(text))
    if n_sent > max_sentences:
        fails.append(f"too_long({n_sent}>{max_sentences})")
    if text.count("?") > 2:
        fails.append("too_many_questions")
    if allowed_packages is not None:
        bad = {m.lower() for m in PACKAGE_RE.findall(text)} - {p.lower() for p in allowed_packages}
        if bad:
            fails.append("invented_package:" + ",".join(sorted(bad)))
    for needle in must_contain or []:
        if needle.lower() not in text.lower():
            fails.append(f"missing:{needle}")
    for needle in must_not_contain or []:
        if needle.lower() in text.lower():
            fails.append(f"forbidden:{needle}")
    return fails


# --- rendering a case ----------------------------------------------------------------------


def _fixture_ticket(cfg: Config, case: dict) -> dict:
    ticket_id = f"{cfg.ticket_prefix}-0007"
    level = replace(ladder.get_level(int(case.get("level", 1))), seed="sales-summary")
    spec = seeds.seed(cfg, level, ticket_id)
    assert spec is not None
    return {
        "id": ticket_id,
        "title": spec["title"],
        "client": spec["client"],
        "status": "open",
        "due_local": "Thu 10 Sep 17:00",
        "brief": spec["brief"],
        "acceptance": spec["acceptance"],
        "boss_notes": spec["boss_notes"],
        "packages": set(ladder.get_level(int(case.get("level", 1))).packages),
    }


def render_case(cfg: Config, case: dict) -> tuple[str, dict]:
    t = _fixture_ticket(cfg, case)
    inp = case.get("inputs", {})
    name = case["prompt"]
    if name == "desk":
        user = render(
            "desk",
            tutor_name=desk.tutor_name(cfg),
            engineer_name=cfg.engineer_name,
            boss_name=cfg.boss_name,
            ticket_id=t["id"],
            title=t["title"],
            client=t["client"],
            status=t["status"],
            due=t["due_local"],
            brief=t["brief"][:1500],
            acceptance="\n".join(f"- {a}" for a in t["acceptance"]),
            history=inp.get("history", ""),
            question=inp["question"],
        )
    elif name == "standup":
        user = render(
            "standup",
            engineer_name=cfg.engineer_name,
            date="Wednesday 09 September",
            yesterday=inp.get("yesterday", "(blank)"),
            today_plan=inp.get("today", "(blank)"),
            blockers=inp.get("blockers", "(none)"),
            open_ticket=(
                f"{t['id']} {t['title']} ({t['client']}), status open, due {t['due_local']}\n"
                f"The brief, so you only refer to what the ticket says:\n{t['brief'][:1200]}"
            ),
            boss_name=cfg.boss_name,
        )
    elif name == "nudge":
        user = render(
            "nudge",
            ticket_id=t["id"],
            title=t["title"],
            client=t["client"],
            due="Thursday 17:00",
            overdue=inp.get("overdue", 1),
            boss_name=cfg.boss_name,
            engineer_name=cfg.engineer_name,
        )
    elif name == "desk_note":
        user = render(
            "desk_note",
            engineer_name=cfg.engineer_name,
            boss_name=cfg.boss_name,
            text=inp["text"],
            open_ticket=(
                f"{t['id']} {t['title']} ({t['client']}), status open, due {t['due_local']}"
            ),
        )
    elif name == "review":
        user = render(
            "review",
            engineer_name=cfg.engineer_name,
            ticket_id=t["id"],
            title=t["title"],
            client=t["client"],
            brief=t["brief"],
            acceptance="\n".join(f"- {a}" for a in t["acceptance"]),
            boss_notes=t["boss_notes"],
            message=inp.get("message", "(no message)"),
            tests_status=inp.get("tests_status", "PASS"),
            tests_output=inp.get("tests_output", "3 passed in 0.12s"),
            ruff_status=inp.get("ruff_status", "PASS"),
            ruff_output=inp.get("ruff_output", "All checks passed!"),
            diff=inp.get("diff", "(diff omitted)"),
            corpus_block=inp.get("corpus_block", "(none)"),
            standards=render("standards", company_name=cfg.company),
        )
    else:
        raise ValueError(f"unknown prompt {name}")
    return user, t


def load_cases(path: Path = CASES_PATH) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


# --- run and replay ----------------------------------------------------------------------------

JUDGE_PROMPT = """You audit one message written by a simulated boss to the one person they
manage. Return ONLY JSON: {{"fail": true|false, "contradiction": "..." or null,
"invented": "..." or null, "voice": "human|generated", "reason": "one sentence"}}.
fail is true when the message contradicts itself (for example refusing something and then
granting it), states a tool, API, library, file or number that the context below does not
contain, or reads like generated text (filler, hedging, lists of options, motivational lines).

Context the boss was given:
{context}

Her message:
{message}
"""


def judge(llm: LLM, context: str, message: str) -> dict:
    reply = llm.quality(
        "You are a strict, terse reviewer of prose. JSON only.",
        JUDGE_PROMPT.format(context=context[-4000:], message=message[-3000:]),
        purpose="eval judge",
    )
    if not reply.ok:
        return {"fail": False, "skipped": reply.error}
    try:
        return extract_json(reply.text)
    except ValueError:
        return {"fail": False, "skipped": "unparseable judge reply"}


def run(
    cfg: Config,
    state: State,
    llm: LLM,
    *,
    only: str | None = None,
    lane: str = "cheap",
    use_judge: bool = False,
    limit: int | None = None,
) -> list[Result]:
    results: list[Result] = []
    cases = [c for c in load_cases() if not only or c["prompt"] == only]
    if limit:
        cases = cases[:limit]
    system = system_prompt(cfg, state)
    for case in cases:
        user, t = render_case(cfg, case)
        if lane == "quality":
            reply = llm.quality(system, user, purpose=f"eval {case['id']}")
        else:
            reply = llm.cheap(system, user, purpose=f"eval {case['id']}")
        if not reply.ok:
            results.append(
                Result(
                    case["id"], case["prompt"], case.get("kind", "chat"), "", skipped=reply.error
                )
            )
            continue
        text = reply.text.strip()
        if case["prompt"] == "review":
            with contextlib.suppress(ValueError):
                text = str(extract_json(text).get("feedback_md") or "")
        exp = case.get("expect", {})
        fails = check(
            text,
            case.get("kind", "chat"),
            allowed_packages=t["packages"],
            max_sentences=int(exp.get("max_sentences", 8)),
            engineer=cfg.engineer_name,
            boss_first=cfg.boss_first,
            must_contain=[
                str(m).replace("$tutor_name", desk.tutor_name(cfg))
                for m in exp.get("must_contain") or []
            ],
            must_not_contain=exp.get("must_not_contain"),
        )
        r = Result(case["id"], case["prompt"], case.get("kind", "chat"), text, fails)
        if use_judge:
            r.judge = judge(llm, user, text)
        results.append(r)
    return results


def replay(
    cfg: Config, state: State, llm: LLM | None = None, *, use_judge: bool = False, limit: int = 30
) -> list[Result]:
    """Deterministic checks over what the boss already sent. No model calls unless use_judge."""
    results: list[Result] = []
    for r in state.recent_reviews(limit):
        text = r["feedback_md"] or ""
        results.append(
            Result(
                f"review:{r['ticket_id']}#{r['id']}",
                "review",
                "review",
                text,
                check(
                    text,
                    "review",
                    engineer=cfg.engineer_name,
                    boss_first=cfg.boss_first,
                    max_sentences=40,
                ),
            )
        )
    for m in state.meetings():
        if m["type"] == "standup" and m["minutes"]:
            results.append(
                Result(
                    f"standup:{m['id']}",
                    "standup",
                    "chat",
                    m["minutes"],
                    check(
                        m["minutes"], "chat", engineer=cfg.engineer_name, boss_first=cfg.boss_first
                    ),
                )
            )
    for row in state.answered_desk_questions(limit):
        kind = "chat" if row["kind"] == "boss_question" else "chat"
        results.append(
            Result(
                f"desk:{row['id'][:8]}",
                row["kind"],
                kind,
                row["answer"],
                check(row["answer"], kind, engineer=cfg.engineer_name, boss_first=cfg.boss_first),
            )
        )
    for msg in state.messages(limit):
        if msg["kind"] in {"nudge", "ticket"}:
            results.append(
                Result(
                    f"{msg['kind']}:{msg['id']}",
                    msg["kind"],
                    "mail",
                    msg["body"],
                    check(
                        msg["body"],
                        "mail",
                        engineer=cfg.engineer_name,
                        boss_first=cfg.boss_first,
                        max_sentences=60,
                    ),
                )
            )
    if use_judge and llm is not None:
        for res in results:
            res.judge = judge(llm, "(replayed output; context not available)", res.output)
    return results


def report(cfg: Config, results: list[Result], title: str) -> Path:
    out_dir = cfg.root / "evals"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M")
    path = out_dir / f"{stamp}-{title}.md"
    passed = sum(1 for r in results if r.ok)
    lines = [f"# Eval {title} {stamp}", "", f"{passed}/{len(results)} passed", ""]
    for r in results:
        status = "PASS" if r.ok else ("SKIP" if r.skipped else "FAIL")
        detail = r.skipped or ", ".join(r.failures) or ""
        if r.judge and r.judge.get("fail"):
            detail += f" | judge: {r.judge.get('reason', '')}"
        lines.append(f"## {status} {r.case_id} ({r.prompt}) {detail}".rstrip())
        lines.append("")
        lines.append(r.output.strip() or "(no output)")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
