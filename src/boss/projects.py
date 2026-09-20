"""Internal project series: long-running library work the boss interleaves with client tickets.

Each series is a list of milestones in the track file. The generator hands out the next
unfinished milestone when the level fits and the previous ticket was a client ticket, so the
week alternates between "a client needs X" and "our own library needs its next piece".
"""

from __future__ import annotations

from boss import tracks
from boss.state import State
from boss.tracks import Series


def __getattr__(name: str):
    if name == "SERIES":
        return tracks.active().series
    raise AttributeError(name)


def series_for_level(level: int) -> list[Series]:
    return [s for s in tracks.active().series if s.levels[0] <= level <= s.levels[1]]


def done_milestones(state: State, key: str) -> int:
    return int(state.get_meta(f"series:{key}:done", "0") or 0)


def next_milestone(state: State, level: int) -> tuple[Series, int, str] | None:
    """The first series at this level with an unfinished milestone, plus its index and text."""
    for s in series_for_level(level):
        idx = done_milestones(state, s.key)
        if idx < len(s.milestones):
            return s, idx, s.milestones[idx]
    return None


def mark_milestone_done(state: State, key: str, idx: int) -> None:
    current = done_milestones(state, key)
    if idx + 1 > current:
        state.set_meta(f"series:{key}:done", str(idx + 1))


def series_block(s: Series, idx: int) -> str:
    done = ", ".join(s.milestones[:idx]) or "none yet"
    lines = [
        f"Internal project, paid by the company itself: {s.name}.",
        f"Goal: {s.goal}",
        "Constraints: " + " | ".join(s.constraints),
        f"Milestones already delivered: {done}.",
        f"THIS ticket delivers milestone {idx + 1} of {len(s.milestones)}: {s.milestones[idx]}.",
        "The sandbox for this ticket starts empty except for your tests and data; they "
        "bring forward their own code from the previous milestone's sandbox by copying it "
        "in themselves (say so in the brief).",
    ]
    return "\n".join(lines)
