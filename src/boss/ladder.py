"""The level ladder of the active track: what the boss may assign at each level and when
the learner moves up. Levels are coarse on purpose: one ticket trains one or two competencies.
The data lives in the track file (see tracks.py); this module is the read side.
"""

from __future__ import annotations

import re
from pathlib import Path

from boss import tracks
from boss.tracks import Level

__all__ = ["Level", "get_level", "is_top", "progress_hints"]


def __getattr__(name: str):
    if name == "LEVELS":
        return tracks.active().levels
    if name == "COMMON":
        return tracks.active().common_packages
    raise AttributeError(name)


def get_level(number: int) -> Level:
    levels = tracks.active().levels
    return levels[max(0, min(number, len(levels) - 1))]


def is_top(number: int) -> bool:
    return number >= len(tracks.active().levels) - 1


CHECKBOX_RE = re.compile(r"^\s*-\s*\[( |x|X)\]\s*(.+)$")


def progress_hints(progress_md: Path | None) -> str:
    """Summarise the study tracker's checkboxes per heading. Empty string if absent."""
    if progress_md is None or not progress_md.exists():
        return "(no study tracker found)"
    heading, done, total, lines = "", 0, 0, []
    for line in progress_md.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            if heading and total:
                lines.append(f"- {heading}: {done}/{total} ticked")
            heading, done, total = line[3:].strip(), 0, 0
            continue
        m = CHECKBOX_RE.match(line)
        if m:
            total += 1
            done += m.group(1).lower() == "x"
    if heading and total:
        lines.append(f"- {heading}: {done}/{total} ticked")
    return "\n".join(lines) or "(tracker has no checkboxes)"
