"""boss.toml plus the private env file, exposed as one Config object."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from boss import tracks

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parents[1]  # .../boss
CONFIG_DIR = Path(os.environ.get("BOSS_CONFIG_DIR") or "~/.config/fenrir-boss").expanduser()
ENV_FILE = CONFIG_DIR / "boss.env"


def default_toml() -> Path:
    """$BOSS_TOML, else ./boss.toml when present, else the per-user config directory."""
    if os.environ.get("BOSS_TOML"):
        return Path(os.environ["BOSS_TOML"]).expanduser()
    local = Path.cwd() / "boss.toml"
    return local if local.exists() else CONFIG_DIR / "boss.toml"


SECRET_KEYS = (
    "GROQ_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "LLM_API_KEY",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USER",
    "SMTP_PASSWORD",
    "SMTP_FROM",
    "SMTP_TO",
    "SMTP2_HOST",
    "SMTP2_PORT",
    "SMTP2_USER",
    "SMTP2_PASSWORD",
    "SMTP2_FROM",
    "SMTP2_TO",
    "NTFY_TOPIC",
)


class ConfigError(RuntimeError):
    pass


def load_env_file(path: Path) -> dict[str, str]:
    """Parse KEY=value lines. Quotes stripped, comments and blanks ignored, missing file = {}."""
    out: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return out
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.startswith("export "):
            key = key[7:]
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


@dataclass(frozen=True)
class Config:
    data: dict
    toml_path: Path

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        toml_path = Path(path) if path else default_toml()
        try:
            with toml_path.open("rb") as fh:
                data = tomllib.load(fh)
        except FileNotFoundError as exc:
            raise ConfigError(f"no settings at {toml_path}; run `boss setup` first") from exc
        if "learner" in data and "engineer" not in data:
            data["engineer"] = data["learner"]
        for table in ("company", "boss", "engineer", "paths"):
            if table not in data:
                raise ConfigError(f"{toml_path}: missing [{table}]; run `boss setup` again")
        cfg = cls(data=data, toml_path=toml_path)
        tracks.activate(cfg.track_name, cfg.root)
        return cfg

    def section(self, name: str) -> dict:
        return dict(self.data.get(name, {}))

    # --- paths -------------------------------------------------------------
    @property
    def root(self) -> Path:
        raw = os.environ.get("BOSS_ROOT") or self.data["paths"]["root"]
        return Path(raw).expanduser().resolve()

    @property
    def db_path(self) -> Path:
        return self.root / "state" / "boss.sqlite3"

    @property
    def tickets_dir(self) -> Path:
        return self.root / "tickets"

    @property
    def inbox_dir(self) -> Path:
        return self.root / "inbox"

    @property
    def calendar_dir(self) -> Path:
        return self.root / "calendar"

    @property
    def meetings_dir(self) -> Path:
        return self.root / "meetings"

    # --- simulation -------------------------------------------------------
    @property
    def track_name(self) -> str:
        return str(self.section("sim").get("track") or tracks.DEFAULT_TRACK)

    @property
    def setting(self) -> str:
        """company (a boss and tickets) or school (an instructor and assignments)."""
        value = str(self.section("sim").get("setting", "company")).lower()
        return value if value in {"company", "school"} else "company"

    @property
    def role(self) -> str:
        """What the learner is training to become; the track's role unless overridden."""
        return str(self.section("sim").get("role") or tracks.active().role or "engineer")

    @property
    def pronouns(self) -> str:
        return str(self.data["engineer"].get("pronouns", "they/them"))

    # --- people ------------------------------------------------------------
    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.data["engineer"].get("timezone", "UTC"))

    @property
    def engineer_name(self) -> str:
        return self.data["engineer"]["name"]

    @property
    def boss_name(self) -> str:
        return self.data["boss"]["name"]

    @property
    def boss_first(self) -> str:
        return self.boss_name.split()[0]

    @property
    def company(self) -> str:
        return self.data["company"]["name"]

    @property
    def ticket_prefix(self) -> str:
        return self.data["company"].get("ticket_prefix", "TKT")

    @property
    def meeting_prefix(self) -> str:
        return self.data["company"].get("meeting_prefix", "MTG")

    # --- secrets -----------------------------------------------------------
    @property
    def secrets(self) -> dict[str, str]:
        """Private env file first, optional fallback files second, process env wins."""
        env = load_env_file(ENV_FILE)
        for extra in self.section("llm").get("fallback_env_files", []):
            for key, value in load_env_file(Path(extra).expanduser()).items():
                env.setdefault(key, value)
        for key in SECRET_KEYS:
            if os.environ.get(key):
                env[key] = os.environ[key]
        return env

    # --- rules -------------------------------------------------------------
    @property
    def reviews_may_contain_code(self) -> bool:
        return bool(self.section("rules").get("reviews_may_contain_code", False))

    @property
    def quiet_hours(self) -> tuple[int, int]:
        start, end = self.section("rules").get("quiet_hours", [22, 7])
        return int(start), int(end)
