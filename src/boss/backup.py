"""A daily copy of the boss's memory: the state database (notebook, reviews, meetings) and
the text record, into `[backup] local_dir` (14 dated folders kept), and with a self-hosted
desk and `offsite = true` also to that server over rsync."""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

from boss.config import Config
from boss.state import State

KEEP_DAYS = 14
TEXT_DIRS = ("company", "reviews", "meetings", "inbox", "calendar", "evals")
TEXT_FILES = ("INBOX.md",)


def local_dir(cfg: Config) -> Path:
    raw = cfg.section("backup").get("local_dir") or f"{cfg.root}-backup"
    return Path(raw).expanduser()


def run(cfg: Config, state: State, timeout: int = 120) -> str:
    stamp = datetime.now(cfg.tz).strftime("%Y-%m-%d")
    dest = local_dir(cfg) / stamp
    dest.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(dest / "boss.sqlite3") as target:
        state.conn.backup(target)
    for name in TEXT_DIRS:
        src = cfg.root / name
        if src.is_dir():
            shutil.copytree(src, dest / name, dirs_exist_ok=True)
    for name in TEXT_FILES:
        src = cfg.root / name
        if src.exists():
            shutil.copy2(src, dest / name)
    threads = cfg.root / "desk" / "threads"
    if threads.is_dir():
        shutil.copytree(threads, dest / "desk-threads", dirs_exist_ok=True)
    # keep the last KEEP_DAYS dated folders
    dated = sorted(p for p in local_dir(cfg).iterdir() if p.is_dir() and p.name[:4].isdigit())
    for old in dated[:-KEEP_DAYS]:
        shutil.rmtree(old, ignore_errors=True)
    result = f"backup {stamp} -> {dest}"
    web = cfg.section("web")
    host = web.get("host") if web.get("enabled") else None
    remote = str(cfg.section("desk").get("remote_data", "services/fenrir-boss/data")).rstrip("/")
    if host and cfg.section("backup").get("offsite", False):
        cmd = [
            "rsync",
            "-az",
            "--delete",
            "-e",
            "ssh -o BatchMode=yes -o ConnectTimeout=10",
            f"{local_dir(cfg)}/",
            f"{host}:{remote}/backup/",
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
            result += (
                "; offsite ok"
                if proc.returncode == 0
                else f"; offsite failed: {proc.stderr.strip()[:120]}"
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            result += f"; offsite failed: {type(exc).__name__}"
    return result
