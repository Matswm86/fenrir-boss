"""Ticket generation: LLM-authored and validated, or a built-in seed when the LLM is out."""

from __future__ import annotations

import ast
import json
import re
import shutil
import sys
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

from boss import clients, corpus, ladder, projects, sandbox, seeds
from boss.config import Config
from boss.llm import LLM, extract_json
from boss.persona import render, system_prompt
from boss.safety import SandboxError, safe_relpath
from boss.state import State, now_iso

REQUIRED = {
    "title",
    "slug",
    "client",
    "kind",
    "estimate_hours",
    "due_days",
    "brief",
    "acceptance",
    "learning_goals",
    "dependencies",
    "files",
    "run_command",
    "boss_notes",
    "meeting",
}
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,40}$")


class TicketError(ValueError):
    pass


def stub_violations(source: str, rel: str) -> list[str]:
    """A stub function body may only be a docstring plus pass, ..., or raise."""
    problems: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        body = node.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            body = body[1:]
        for stmt in body:
            allowed = isinstance(stmt, ast.Pass | ast.Raise) or (
                isinstance(stmt, ast.Expr)
                and isinstance(stmt.value, ast.Constant)
                and stmt.value.value is Ellipsis
            )
            if not allowed:
                problems.append(f"{rel}: function {node.name} contains logic; stubs only raise")
                break
    return problems


def validate_spec(spec: dict, level: ladder.Level) -> dict:
    missing = REQUIRED - set(spec)
    if missing:
        raise TicketError(f"missing keys: {sorted(missing)}")
    if spec["kind"] not in {"code", "doc"}:
        raise TicketError("kind must be code or doc")
    if not SLUG_RE.match(str(spec["slug"])):
        raise TicketError("slug must be kebab-case, 3 to 41 chars")
    if "```" in spec["brief"]:
        raise TicketError("brief contains a code fence; describe in plain English instead")
    if not isinstance(spec["files"], dict) or not spec["files"]:
        raise TicketError("files must be a non-empty object")
    if not isinstance(spec["acceptance"], list) or not 2 <= len(spec["acceptance"]) <= 8:
        raise TicketError("acceptance must be a list of 2 to 8 criteria")
    try:
        spec["due_days"] = max(1, min(int(spec["due_days"]), 7))
        spec["estimate_hours"] = float(spec["estimate_hours"])
    except (TypeError, ValueError) as exc:
        raise TicketError(f"due_days / estimate_hours not numeric: {exc}") from exc
    files: dict[str, str] = {}
    for rel, content in spec["files"].items():
        rel = safe_relpath(str(rel))
        if not isinstance(content, str):
            raise TicketError(f"file {rel} content is not a string")
        if rel.endswith(".py"):
            try:
                ast.parse(content)
            except SyntaxError as exc:
                raise TicketError(f"{rel} does not parse: {exc}") from exc
            if rel.startswith("src/"):
                problems = stub_violations(content, rel)
                if problems:
                    raise TicketError("; ".join(problems))
        files[rel] = content
    spec["files"] = files
    if spec["kind"] == "code":
        if not any(re.match(r"tests/test_.+\.py$", r) for r in files):
            raise TicketError("code ticket needs tests/test_*.py")
        if not any(r.startswith("src/") and r.endswith(".py") for r in files):
            raise TicketError("code ticket needs a stub under src/")
        spec["run_command"] = spec.get("run_command") or "uv run pytest -q"
        if not str(spec["run_command"]).startswith("uv run"):
            spec["run_command"] = "uv run " + str(spec["run_command"])
    else:
        spec["run_command"] = None
    allowed = set(level.packages) | set(ladder.COMMON)
    wanted = [str(d).strip().lower() for d in (spec.get("dependencies") or [])]
    kept = [d for d in wanted if d in allowed and d not in ladder.COMMON]
    dropped = [d for d in wanted if d not in allowed]
    spec["dependencies"] = kept
    spec["warnings"] = [f"dropped dependency not on the allowlist: {d}" for d in dropped]
    meeting = spec.get("meeting")
    if meeting is not None:
        if not isinstance(meeting, dict) or meeting.get("type") not in {
            "client_call",
            "one_on_one",
        }:
            raise TicketError(
                "meeting must be null or {type: client_call|one_on_one, in_days, agenda}"
            )
        meeting["in_days"] = max(1, min(int(meeting.get("in_days", 1)), 5))
        meeting["agenda"] = str(meeting.get("agenda") or "Scoping call")
    if level.kind == "doc" and spec["kind"] != "doc":
        raise TicketError("this level issues doc tickets")
    return spec


def _history(state: State) -> tuple[str, list[str], bool]:
    rows = state.tickets()[-8:]
    if not rows:
        return "(none yet)", [], False
    lines = [f"- {r['id']} {r['title']} ({r['client']}, {r['status']})" for r in rows]
    recent_clients = [r["client"] for r in rows]
    last_was_series = '"series"' in (rows[-1]["spec_json"] or "")
    return "\n".join(lines), recent_clients, last_was_series


def _progress_file(cfg: Config) -> Path | None:
    """Optional `[sim] progress_file`: a markdown checklist the learner keeps elsewhere."""
    raw = cfg.section("sim").get("progress_file")
    return Path(str(raw)).expanduser() if raw else None


def _reviewer_hint(state: State) -> str:
    reviews = state.recent_reviews(1)
    if not reviews or not reviews[0]["next_focus"]:
        return ""
    return f"Your last review said their next focus is: {reviews[0]['next_focus']}"


def _llm_spec(cfg: Config, state: State, llm: LLM, level: ladder.Level, seq: int) -> dict | None:
    history, recent_clients, last_was_series = _history(state)
    series = None if last_was_series else projects.next_milestone(state, level.number)
    if series:
        s, idx, _ = series
        client_block, client_name = projects.series_block(s, idx), f"{cfg.company} (internal)"
    else:
        c = clients.pick_client(seq, recent_clients)
        client_block, client_name = clients.client_block(c), c["name"]
    prompt = render(
        "ticket",
        engineer_name=cfg.engineer_name,
        level=level.number,
        level_name=level.name,
        level_phase=level.phase,
        competencies="\n".join(f"- {c}" for c in level.competencies),
        shapes="\n".join(f"- {s}" for s in level.shapes),
        client_block=client_block,
        client_name=client_name,
        history=history,
        progress_hints=ladder.progress_hints(_progress_file(cfg)),
        role=cfg.role,
        reviewer_hint=_reviewer_hint(state),
        corpus_block=corpus.block(cfg, " ".join(level.competencies), k=4) or "(nothing retrieved)",
        standards=render("standards", company_name=cfg.company),
        estimate_hours=level.estimate_hours,
        packages=", ".join(sorted(set(level.packages))),
        extra_rules=level.extra_rules,
        today=datetime.now(cfg.tz).date().isoformat(),
        kind=level.kind,
    )
    system = system_prompt(cfg, state)
    user = prompt
    for attempt in (1, 2):
        reply = llm.quality(system, user, purpose=f"ticket L{level.number} attempt {attempt}")
        if not reply.ok:
            print(f"boss: ticket generation failed ({reply.error})", file=sys.stderr)
            return None
        try:
            spec = validate_spec(extract_json(reply.text), level)
        except (ValueError, SandboxError) as exc:
            print(f"boss: ticket attempt {attempt} rejected: {exc}", file=sys.stderr)
            user = (
                prompt + f"\n\nYour previous JSON was rejected: {exc}. "
                "Fix that and return the whole JSON again."
            )
            continue
        if series:
            spec["series"] = {"key": series[0].key, "index": series[1]}
        return spec
    return None


def generate(
    cfg: Config, state: State, llm: LLM | None, *, force_seed: bool = False, install: bool = True
) -> dict:
    level_no = state.level
    level = ladder.get_level(level_no)
    seq = state.next_seq("ticket")
    ticket_id = f"{cfg.ticket_prefix}-{seq:04d}"
    spec, source = None, "seed"
    if level_no >= 1 and not force_seed and llm is not None and llm.available():
        spec = _llm_spec(cfg, state, llm, level, seq)
        source = "llm"
    if spec is None:
        spec, source = seeds.seed(cfg, level, ticket_id), "seed"
        if spec is None:
            raise TicketError(
                f"no ticket available at level {level_no}: the LLM did not produce one and "
                "this level has no built-in seed. Check `boss doctor --llm`."
            )
        spec = validate_spec(spec, level)
    now = datetime.now(UTC)
    due_day = (now.astimezone(cfg.tz) + timedelta(days=spec["due_days"])).date()
    due = datetime.combine(due_day, time(17, 0), tzinfo=cfg.tz).astimezone(UTC)
    due_local = due.astimezone(cfg.tz).strftime("%A %d %B %Y, %H:%M")
    path, base = sandbox.create(cfg, ticket_id, spec, due_local, install=install and level_no > 0)
    if spec["kind"] == "code" and install and level_no > 0:
        checks = sandbox.run_checks(path, spec["run_command"])
        if checks["tests_ok"]:
            shutil.rmtree(path, ignore_errors=True)
            raise TicketError(f"{ticket_id}: the tests pass on the stub, ticket rejected")
    row = {
        "id": ticket_id,
        "seq": seq,
        "level": level_no,
        "kind": spec["kind"],
        "title": spec["title"],
        "slug": spec["slug"],
        "client": spec["client"],
        "status": "open",
        "created_at": now_iso(),
        "due_at": due.isoformat(timespec="seconds"),
        "sandbox": str(path),
        "base_commit": base,
        "brief": spec["brief"],
        "acceptance": json.dumps(spec["acceptance"]),
        "boss_notes": spec["boss_notes"],
        "run_command": spec["run_command"],
        "spec_json": json.dumps(spec, ensure_ascii=False),
        "source": source,
    }
    state.insert_ticket(row)
    row["spec"] = spec
    return row
