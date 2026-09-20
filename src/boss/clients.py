"""Fictional clients of the active track. Nothing here refers to a real company or person."""

from __future__ import annotations

from boss import tracks


def __getattr__(name: str):
    if name == "CLIENTS":
        return tracks.active().clients
    raise AttributeError(name)


def pick_client(seq: int, recent: list[str]) -> dict:
    """Least-recently-used rotation: skip the clients used most recently."""
    pool = tracks.active().clients
    names = [c["name"] for c in pool]
    for name in reversed(recent[-3:]):
        if name in names:
            names.remove(name)
    chosen = names[seq % len(names)] if names else pool[0]["name"]
    return next(c for c in pool if c["name"] == chosen)


def client_block(c: dict, hidden: bool = False) -> str:
    lines = [
        f"{c['name']}: {c['sector']}. Contact: {c['contact']}, {c['role']}.",
        f"Data they have: {c['data']}",
        f"Situation: {c['situation']}",
    ]
    if hidden:
        lines.append("Hidden facts: " + " | ".join(c["hidden"]))
    return "\n".join(lines)
