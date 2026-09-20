"""Guard rails: paths stay in the sandbox, reviews stay code-free, subprocess env is scrubbed."""

from __future__ import annotations

import os
import re
from pathlib import Path

CODE_FENCE_RE = re.compile(r"```.*?```", re.S)
PY_LINE_RE = re.compile(
    r"^\s*(def |class |import |from \S+ import |for \S+ in .+:\s*$|while .+:\s*$|"
    r"return\b|print\(|lambda |with open\()",
    re.M,
)
# A single name in backticks is fine (`dict.get`); a signature, an expression or a long span
# in backticks is code by another route.
INLINE_SPAN_RE = re.compile(r"`([^`\n]+)`")
INLINE_CODE_MARKS = re.compile(r"->|\s=\s|\)\s*[*+/-]\s*\w|\]\s*[*+/-]\s*\w|\bdef \b|\blambda\b")
WITHHELD = "[code withheld: you type it]"


def _inline(match: re.Match) -> str:
    """Spans are paired left to right, so the prose between two short spans is never a span."""
    span = match.group(1)
    if len(span) >= 40 or INLINE_CODE_MARKS.search(span):
        return WITHHELD
    return match.group(0)


class SandboxError(RuntimeError):
    pass


def ensure_inside(root: Path, path: Path) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise SandboxError(f"{resolved} is outside the sandbox root {root}") from exc
    return resolved


def safe_relpath(rel: str) -> str:
    """A ticket file path must be relative, inside the repo, and plain."""
    p = Path(rel)
    if p.is_absolute() or ".." in p.parts or not p.parts:
        raise SandboxError(f"unsafe ticket path: {rel!r}")
    if any(part.startswith(".") and part not in {".env.example", ".gitignore"} for part in p.parts):
        raise SandboxError(f"hidden path not allowed in a ticket: {rel!r}")
    return p.as_posix()


def strip_code(text: str) -> str:
    """Remove fenced blocks and obvious Python statements from prose."""
    out = CODE_FENCE_RE.sub(WITHHELD, text)
    out = INLINE_SPAN_RE.sub(_inline, out)
    return PY_LINE_RE.sub(WITHHELD, out)


SECRET_PREFIXES = ("ANTHROPIC", "GROQ", "OPENAI", "GEMINI", "GOOGLE", "SMTP", "AWS", "AZURE")


def scrubbed_env() -> dict[str, str]:
    """Environment for running the engineer's code: no provider keys, no boss secrets."""
    return {
        k: v
        for k, v in os.environ.items()
        if not k.upper().startswith(SECRET_PREFIXES) and not k.upper().endswith(("_KEY", "_TOKEN"))
    }
