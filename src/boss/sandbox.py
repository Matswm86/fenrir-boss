"""Sandbox repos: one git repository per ticket under <root>/tickets, and the checks run in it."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from boss.config import Config
from boss.safety import SandboxError, ensure_inside, safe_relpath, scrubbed_env

# The skeleton commit is authored by the boss; the learner's commits use their own git identity.
GIT_ENV = {
    "GIT_AUTHOR_NAME": "The Boss",
    "GIT_AUTHOR_EMAIL": "boss@sandbox.invalid",
    "GIT_COMMITTER_NAME": "The Boss",
    "GIT_COMMITTER_EMAIL": "boss@sandbox.invalid",
}


def set_boss_identity(name: str) -> None:
    GIT_ENV["GIT_AUTHOR_NAME"] = GIT_ENV["GIT_COMMITTER_NAME"] = name or "The Boss"


GITIGNORE = (
    ".venv/\n__pycache__/\n*.pyc\n.pytest_cache/\n.ruff_cache/\n.env\n*.env\n!.env.example\n"
)


def _git(
    path: Path, *args: str, check: bool = True, timeout: int = 60
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(path), *args],
        text=True,
        capture_output=True,
        check=check,
        timeout=timeout,
        env={**scrubbed_env(), **GIT_ENV},
    )


def pyproject_text(name: str, dependencies: list[str]) -> str:
    deps = ", ".join(f'"{d}"' for d in dependencies)
    return (
        "[project]\n"
        f'name = "{name}"\n'
        'version = "0.1.0"\n'
        'requires-python = ">=3.12"\n'
        f"dependencies = [{deps}]\n\n"
        "[dependency-groups]\n"
        'dev = ["pytest", "ruff"]\n\n'
        "[tool.pytest.ini_options]\n"
        'pythonpath = ["src"]\n'
        'testpaths = ["tests"]\n\n'
        "[tool.ruff]\n"
        "line-length = 100\n"
        'target-version = "py312"\n'
    )


def ticket_md(ticket_id: str, spec: dict, due_local: str) -> str:
    acc = "\n".join(f"- [ ] {a}" for a in spec["acceptance"])
    goals = "\n".join(f"- {g}" for g in spec.get("learning_goals", []))
    run = spec.get("run_command") or "(no automated tests: this is a document ticket)"
    return (
        f"# {ticket_id}: {spec['title']}\n\n"
        f"Client: {spec['client']}  \nEstimate: {spec['estimate_hours']} h  \nDue: {due_local}\n\n"
        f"## Brief\n\n{spec['brief'].strip()}\n\n"
        f"## Acceptance criteria\n\n{acc}\n\n"
        f"## What this trains\n\n{goals}\n\n"
        f"## How to work\n\n"
        f"1. `cd` into this folder, `uv sync`, then `{run}`. "
        "Tests fail now; that is the starting line.\n"
        f"2. Type your code. Commit early, commit often, however ugly.\n"
        f"3. When done: `boss submit {ticket_id} "
        '-m "what you did and what you are unsure about"`.\n'
    )


def create(
    cfg: Config, ticket_id: str, spec: dict, due_local: str, *, install: bool
) -> tuple[Path, str]:
    set_boss_identity(cfg.boss_name)
    path = ensure_inside(cfg.root, cfg.tickets_dir / f"{ticket_id}-{spec['slug']}")
    if path.exists():
        raise SandboxError(f"sandbox already exists: {path}")
    path.mkdir(parents=True)
    for rel, content in spec["files"].items():
        target = path / safe_relpath(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content if content.endswith("\n") else content + "\n", encoding="utf-8")
    (path / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
    (path / "TICKET.md").write_text(ticket_md(ticket_id, spec, due_local), encoding="utf-8")
    if not (path / "pyproject.toml").exists():
        (path / "pyproject.toml").write_text(
            pyproject_text(f"{ticket_id.lower()}-{spec['slug']}", spec.get("dependencies", [])),
            encoding="utf-8",
        )
    if "google-genai" in spec.get("dependencies", []) and not (path / ".env.example").exists():
        (path / ".env.example").write_text(
            "GEMINI_API_KEY=paste-your-free-tier-key-here\n", encoding="utf-8"
        )
    if install and shutil.which("uv"):
        subprocess.run(
            ["uv", "sync", "--quiet"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
            env=scrubbed_env(),
        )
    _git(path, "init", "-q", "-b", "main")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", f"{ticket_id}: ticket skeleton")
    base = _git(path, "rev-parse", "HEAD").stdout.strip()
    return path, base


def head(path: Path) -> str:
    return _git(path, "rev-parse", "HEAD").stdout.strip()


def has_engineer_commits(path: Path, base: str) -> bool:
    out = _git(path, "rev-list", "--count", f"{base}..HEAD").stdout.strip()
    return out.isdigit() and int(out) > 0


def is_dirty(path: Path) -> bool:
    return bool(_git(path, "status", "--porcelain").stdout.strip())


def diff_since(path: Path, base: str, cap: int = 40_000) -> str:
    out = _git(path, "diff", f"{base}..HEAD", "--", ".", ":(exclude)uv.lock", check=False).stdout
    if len(out) > cap:
        return out[:cap] + f"\n... [diff truncated at {cap} characters]\n"
    return out or "(no changes committed since the skeleton)"


def log_since(path: Path, base: str) -> str:
    return _git(path, "log", "--oneline", f"{base}..HEAD", check=False).stdout.strip()


def _run(path: Path, args: list[str], timeout: int) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            args,
            cwd=path,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=scrubbed_env(),
        )
    except FileNotFoundError:
        return False, f"{args[0]} not found on PATH"
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s"
    out = (proc.stdout + proc.stderr).strip()
    return proc.returncode == 0, out[-6000:]


def run_checks(path: Path, run_command: str | None) -> dict:
    """pytest (if the ticket has one) and ruff, both inside the sandbox venv."""
    result: dict = {"tests_ok": None, "tests_output": "", "ruff_ok": None, "ruff_output": ""}
    if run_command:
        ok, out = _run(
            path, ["uv", "run", "--quiet", *run_command.replace("uv run ", "").split()], 240
        )
        result["tests_ok"], result["tests_output"] = ok, out
    ok, out = _run(path, ["uv", "run", "--quiet", "ruff", "check", "."], 120)
    result["ruff_ok"], result["ruff_output"] = ok, out
    return result
