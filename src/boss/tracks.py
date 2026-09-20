"""Tracks: the curriculum as data. One file holds the level ladder, the fictional clients and
the internal project series for one career path.

Built-in tracks live beside this module in `tracks/*.toml`. Your own go in `<root>/tracks/`
as `.toml` or `.json` (`boss track new` writes JSON there), or anywhere on disk when
`[sim] track` in boss.toml is a path. One track is active per process; `ladder`, `clients`
and `projects` read from it.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

BUILTIN_DIR = Path(__file__).resolve().parent / "tracks"
DEFAULT_TRACK = "python-foundations"


class TrackError(ValueError):
    pass


@dataclass(frozen=True)
class Level:
    number: int
    name: str
    phase: str
    competencies: tuple[str, ...]
    shapes: tuple[str, ...]
    packages: tuple[str, ...]
    required_accepted: int
    estimate_hours: str
    gate_questions: tuple[str, ...]
    extra_rules: str = ""
    kind: str = "code"
    seed: str = ""


@dataclass(frozen=True)
class Series:
    key: str
    name: str
    levels: tuple[int, int]
    goal: str
    constraints: tuple[str, ...]
    milestones: tuple[str, ...]


@dataclass(frozen=True)
class Track:
    key: str
    name: str
    summary: str
    role: str
    common_packages: tuple[str, ...]
    levels: tuple[Level, ...]
    clients: tuple[dict, ...]
    series: tuple[Series, ...] = field(default_factory=tuple)
    source: str = ""


def _strs(value: object, where: str, *, required: bool = True) -> tuple[str, ...]:
    if value is None and not required:
        return ()
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise TrackError(f"{where} must be a list of non-empty strings")
    if required and not value:
        raise TrackError(f"{where} must not be empty")
    return tuple(v.strip() for v in value)


def _text(table: dict, key: str, where: str, default: str | None = None) -> str:
    value = table.get(key, default)
    if not isinstance(value, str) or (default is None and not value.strip()):
        raise TrackError(f"{where}.{key} must be a non-empty string")
    return value.strip()


def parse(data: dict, source: str = "") -> Track:
    """Validate a decoded track file. Raises TrackError with the offending field named."""
    if not isinstance(data, dict):
        raise TrackError("a track is one table/object")
    head = data.get("track")
    if not isinstance(head, dict):
        raise TrackError("missing [track] table")
    common = _strs(head.get("common_packages", ["pytest", "ruff"]), "track.common_packages")
    raw_levels = data.get("levels")
    if not isinstance(raw_levels, list) or len(raw_levels) < 2:
        raise TrackError("a track needs at least two [[levels]] (L0 onboarding plus one more)")
    levels: list[Level] = []
    for i, lv in enumerate(raw_levels):
        where = f"levels[{i}]"
        if not isinstance(lv, dict):
            raise TrackError(f"{where} must be a table")
        kind = str(lv.get("kind", "code"))
        if kind not in {"code", "doc"}:
            raise TrackError(f"{where}.kind must be code or doc")
        try:
            required = int(lv.get("required_accepted", 3))
        except (TypeError, ValueError) as exc:
            raise TrackError(f"{where}.required_accepted must be a number") from exc
        levels.append(
            Level(
                number=i,
                name=_text(lv, "name", where),
                phase=_text(lv, "phase", where, ""),
                competencies=_strs(lv.get("competencies"), f"{where}.competencies"),
                shapes=_strs(lv.get("shapes"), f"{where}.shapes"),
                packages=tuple(
                    dict.fromkeys(
                        common + _strs(lv.get("packages"), f"{where}.packages", required=False)
                    )
                ),
                required_accepted=max(1, min(required, 20)),
                estimate_hours=str(lv.get("estimate_hours", "1 to 2")),
                gate_questions=_strs(lv.get("gate_questions"), f"{where}.gate_questions"),
                extra_rules=_text(lv, "extra_rules", where, ""),
                kind=kind,
                seed=_text(lv, "seed", where, ""),
            )
        )
    raw_clients = data.get("clients")
    if raw_clients is None:
        with (BUILTIN_DIR / "_clients.toml").open("rb") as fh:
            raw_clients = tomllib.load(fh)["clients"]
    if not isinstance(raw_clients, list) or len(raw_clients) < 2:
        raise TrackError("a track needs at least two [[clients]] (or none, for the default pool)")
    clients: list[dict] = []
    for i, c in enumerate(raw_clients):
        where = f"clients[{i}]"
        if not isinstance(c, dict):
            raise TrackError(f"{where} must be a table")
        clients.append(
            {
                "name": _text(c, "name", where),
                "sector": _text(c, "sector", where),
                "contact": _text(c, "contact", where),
                "role": _text(c, "role", where),
                "data": _text(c, "data", where),
                "situation": _text(c, "situation", where),
                "hidden": list(_strs(c.get("hidden"), f"{where}.hidden")),
            }
        )
    series: list[Series] = []
    for i, s in enumerate(data.get("series") or []):
        where = f"series[{i}]"
        if not isinstance(s, dict):
            raise TrackError(f"{where} must be a table")
        span = s.get("levels")
        if (
            not isinstance(span, list)
            or len(span) != 2
            or not all(isinstance(n, int) for n in span)
            or span[0] > span[1]
        ):
            raise TrackError(f"{where}.levels must be [first_level, last_level]")
        series.append(
            Series(
                key=_text(s, "key", where),
                name=_text(s, "name", where),
                levels=(span[0], span[1]),
                goal=_text(s, "goal", where),
                constraints=_strs(s.get("constraints"), f"{where}.constraints"),
                milestones=_strs(s.get("milestones"), f"{where}.milestones"),
            )
        )
    return Track(
        key=_text(head, "key", "track"),
        name=_text(head, "name", "track"),
        summary=_text(head, "summary", "track", ""),
        role=_text(head, "role", "track", ""),
        common_packages=common,
        levels=tuple(levels),
        clients=tuple(clients),
        series=tuple(series),
        source=source,
    )


def load_file(path: Path) -> Track:
    try:
        if path.suffix == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            with path.open("rb") as fh:
                data = tomllib.load(fh)
    except (json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        raise TrackError(f"{path}: {exc}") from exc
    return parse(data, source=str(path))


def search_dirs(root: Path | None) -> list[Path]:
    return ([root / "tracks"] if root else []) + [BUILTIN_DIR]


def find(name: str, root: Path | None = None) -> Path:
    """A path, or a key looked up in <root>/tracks first and the built-ins second."""
    direct = Path(name).expanduser()
    if direct.suffix in {".toml", ".json"} and direct.exists():
        return direct
    for folder in search_dirs(root):
        for suffix in (".toml", ".json"):
            candidate = folder / f"{name}{suffix}"
            if candidate.exists():
                return candidate
    known = ", ".join(sorted(available(root)))
    raise TrackError(f"no track named {name!r}; available: {known}")


def available(root: Path | None = None) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for folder in reversed(search_dirs(root)):
        if folder.is_dir():
            for path in sorted(folder.iterdir()):
                if path.suffix in {".toml", ".json"} and not path.name.startswith("_"):
                    found[path.stem] = path
    return found


_active: Track | None = None


def activate(name: str = DEFAULT_TRACK, root: Path | None = None) -> Track:
    global _active
    _active = load_file(find(name, root))
    return _active


def active() -> Track:
    return _active or activate()
