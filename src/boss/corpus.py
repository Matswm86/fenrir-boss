"""Retrieval over the learner's own study material, so the boss and the tutor name real
sources instead of inventing them.

`[corpus] dirs` in boss.toml lists folders of notes or transcripts (.md / .txt). Stdlib
only: files are cut into overlapping word windows and ranked with BM25. The index is a
JSON cache next to the state database, rebuilt when a transcript changes.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from boss.config import Config

WINDOW_WORDS = 180
STEP_WORDS = 140
K1, B = 1.5, 0.75
TOKEN_RE = re.compile(r"[a-z0-9_]+")
STOP = frozenset(
    [
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "to",
        "in",
        "is",
        "it",
        "that",
        "this",
        "you",
        "your",
        "for",
        "on",
        "with",
        "as",
        "be",
        "are",
        "was",
        "we",
        "i",
        "so",
        "if",
        "at",
        "by",
        "from",
        "not",
        "but",
        "they",
        "have",
        "has",
        "can",
        "do",
        "does",
        "will",
        "just",
        "like",
        "what",
        "which",
        "when",
        "there",
        "then",
        "here",
        "how",
        "all",
        "one",
        "two",
        "out",
        "up",
        "get",
        "got",
        "into",
        "than",
        "them",
        "their",
        "these",
        "those",
        "about",
        "also",
        "more",
        "some",
        "any",
        "our",
        "its",
        "very",
        "would",
        "could",
        "should",
    ]
)

# File stems to skip, from `[corpus] exclude` in boss.toml.
DEFAULT_EXCLUDE: tuple[str, ...] = ()

# No default folders: the corpus is the learner's own notes or transcripts, set in boss.toml.
DEFAULT_DIRS: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Hit:
    source: str
    video_id: str
    title: str
    text: str
    score: float

    @property
    def url(self) -> str:
        """A link only for video transcripts (a folder with videos_meta.txt); else the file id."""
        return self.video_id if "/" in self.video_id else f"https://youtu.be/{self.video_id}"


def _stem(t: str) -> str:
    """Just enough stemming for 'loops' to meet 'loop' and 'reading' to meet 'read'."""
    for suffix in ("ing", "ies", "es", "ed", "s"):
        if len(t) > len(suffix) + 3 and t.endswith(suffix):
            return t[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return t


def tokens(text: str) -> list[str]:
    return [_stem(t) for t in TOKEN_RE.findall(text.lower()) if t not in STOP and len(t) > 1]


def _titles(folder: Path) -> dict[str, str]:
    """videos_meta.txt lines are id|title|seconds|views|..."""
    out: dict[str, str] = {}
    for name in ("videos_meta.txt", "videos.txt"):
        p = folder / name
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.split("|")
            if len(parts) >= 2 and parts[0].strip():
                out.setdefault(parts[0].strip(), parts[1].strip())
    return out


HEADING_RE = re.compile(r"^#\s+(.+)$", re.M)


def _files(folder: Path) -> list[Path]:
    """Video layout: <folder>/transcripts/*.txt. Otherwise every .md and .txt under the folder."""
    tdir = folder / "transcripts"
    if tdir.is_dir():
        return sorted(tdir.glob("*.txt"))
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.rglob("*") if p.suffix in {".md", ".txt"} and p.is_file())


def _doc(folder: Path, path: Path, titles: dict[str, str], text: str) -> tuple[str, str]:
    """(id, title). Notes get their relative path as id and their first heading as title."""
    if (folder / "transcripts").is_dir():
        return path.stem, titles.get(path.stem, path.stem)
    rel = "./" + str(path.relative_to(folder))
    heading = HEADING_RE.search(text[:2000])
    return rel, heading.group(1).strip() if heading else path.stem.replace("-", " ").replace(
        "_", " "
    )


def _excluded(cfg: Config) -> set[str]:
    return {str(v) for v in cfg.section("corpus").get("exclude_ids", DEFAULT_EXCLUDE)}


def _sources(cfg: Config) -> list[tuple[str, Path]]:
    raw = cfg.section("corpus").get("dirs")
    pairs = [(d["name"], d["path"]) for d in raw] if raw else list(DEFAULT_DIRS)
    return [(name, Path(path).expanduser()) for name, path in pairs]


def _signature(sources: list[tuple[str, Path]]) -> str:
    parts = []
    for name, folder in sources:
        for p in _files(folder):
            st = p.stat()
            parts.append(f"{name}:{p.name}:{st.st_size}:{int(st.st_mtime)}")
    return f"v1:{len(parts)}:{hash(tuple(parts)) & 0xFFFFFFFF:x}"


def build_index(sources: list[tuple[str, Path]], exclude: set[str] | None = None) -> dict:
    chunks: list[dict] = []
    df: Counter = Counter()
    exclude = exclude or set()
    for name, folder in sources:
        titles = _titles(folder)
        for p in _files(folder):
            raw = p.read_text(encoding="utf-8", errors="replace")
            vid, title = _doc(folder, p, titles, raw)
            if vid in exclude or p.stem in exclude:
                continue
            words = raw.split()
            for start in range(0, max(1, len(words) - WINDOW_WORDS + STEP_WORDS), STEP_WORDS):
                window = words[start : start + WINDOW_WORDS]
                if len(window) < 30:
                    continue
                text = " ".join(window)
                toks = tokens(text)
                tf = Counter(toks)
                for t in tokens(title):  # a title word counts three times
                    tf[t] += 3
                chunks.append(
                    {"s": name, "v": vid, "t": title, "x": text, "tf": dict(tf), "n": len(toks)}
                )
                for term in tf:
                    df[term] += 1
    avg = (sum(c["n"] for c in chunks) / len(chunks)) if chunks else 1.0
    return {"chunks": chunks, "df": dict(df), "avg": avg, "N": len(chunks)}


def load_index(cfg: Config, rebuild: bool = False) -> dict:
    sources = _sources(cfg)
    cache = cfg.root / "state" / "corpus_index.json"
    sig = _signature(sources) + ":" + ",".join(sorted(_excluded(cfg))) + ":stem1"
    if not rebuild and cache.exists():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            if data.get("sig") == sig:
                return data
        except (json.JSONDecodeError, OSError):
            pass
    data = build_index(sources, _excluded(cfg))
    data["sig"] = sig
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data), encoding="utf-8")
    return data


def search(cfg: Config, query: str, k: int = 4, per_video: int = 1) -> list[Hit]:
    """Top chunks by BM25, at most `per_video` per video so one long transcript cannot
    crowd out the rest."""
    index = load_index(cfg)
    q = tokens(query)
    if not q or not index["N"]:
        return []
    N, avg, df = index["N"], index["avg"], index["df"]
    scored: list[tuple[float, dict]] = []
    for c in index["chunks"]:
        s = 0.0
        for term in q:
            f = c["tf"].get(term)
            if not f:
                continue
            idf = math.log(1 + (N - df.get(term, 0) + 0.5) / (df.get(term, 0) + 0.5))
            s += idf * (f * (K1 + 1)) / (f + K1 * (1 - B + B * c["n"] / avg))
        if s > 0:
            scored.append((s, c))
    scored.sort(key=lambda t: -t[0])
    out: list[Hit] = []
    seen: Counter = Counter()
    for s, c in scored:
        if seen[c["v"]] >= per_video:
            continue
        seen[c["v"]] += 1
        out.append(Hit(c["s"], c["v"], c["t"], c["x"], round(s, 2)))
        if len(out) >= k:
            break
    return out


def block(cfg: Config, query: str, k: int = 3, chars: int = 500) -> str:
    """Prompt-ready lines: source, title, link, a snippet. Empty string when nothing matches."""
    if not cfg.section("corpus").get("enabled", True):
        return ""
    try:
        hits = search(cfg, query, k=k)
    except OSError:
        return ""
    if not hits:
        return ""
    lines = []
    for h in hits:
        snippet = h.text[:chars].rsplit(" ", 1)[0]
        lines.append(f'- [{h.source}] "{h.title}" ({h.url}): "{snippet}..."')
    return "\n".join(lines)
