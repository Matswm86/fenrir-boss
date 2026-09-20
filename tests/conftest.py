"""One settings file for the whole suite, written by the same code `boss setup` uses."""

from __future__ import annotations

from pathlib import Path

import pytest

from boss import wizard
from boss.config import Config

ANSWERS = {
    **{k: wizard.DEFAULTS["company"][k] for k in ("company", "boss", "title", "city")},
    "setting": "company",
    "intensity": "firm",
    "style": wizard.DEFAULTS["company"]["style"],
    "background": wizard.DEFAULTS["company"]["background"],
    "bible": "ragnhild-varg",
    "tutor": "Mimir",
    "name": "Sam",
    "pronouns": "they/them",
    "timezone": "Europe/Oslo",
    "hours": 7,
    "track": "ai-engineer",
    "role": "",
    "provider": "claude-cli",
    "quality_model": "sonnet",
    "cheap_model": "haiku",
}


@pytest.fixture
def toml_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "root"
    path = tmp_path / "boss.toml"
    path.write_text(wizard.render_toml({**ANSWERS, "root": str(root)}), encoding="utf-8")
    monkeypatch.setenv("BOSS_TOML", str(path))
    monkeypatch.setenv("BOSS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.delenv("BOSS_ROOT", raising=False)
    monkeypatch.setenv("SMTP_HOST", "")
    return path


@pytest.fixture
def cfg(toml_path: Path) -> Config:
    return Config.load()
