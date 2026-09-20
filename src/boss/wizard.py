"""`boss setup`: ask who the company, the boss and the learner are, then write boss.toml.

Everything has a default, so `boss setup --yes` gives a working simulation in one command.
Every question is also a flag, so it scripts. Secrets never go in boss.toml; they go in the
private env file beside it (mode 600).
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from collections.abc import Callable
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from boss import tracks
from boss.config import CONFIG_DIR, ENV_FILE

SETTINGS = {
    "company": "a company: a boss, tickets from clients, reviews, standups, a Friday 1:1",
    "school": "a school: an instructor who sets the same tickets and explains the why in reviews",
}
INTENSITIES = ("kind", "firm", "brutal")
DEFAULTS = {
    "company": {
        "company": "FENRIR AI",
        "boss": "Ragnhild Varg",
        "title": "Head of Engineering",
        "city": "Bergen",
        "intensity": "firm",
        "bible": "ragnhild-varg",
        "style": "direct, clipped, relentless about standards, dry humour, zero small talk",
        "background": "20 years shipping systems for banks and shipping companies, built and "
        "sold one consultancy, fired three clients for lying about their data",
    },
    "school": {
        "company": "Fenrir Academy",
        "boss": "Tobias Lind",
        "title": "Lead Instructor",
        "city": "Gothenburg",
        "intensity": "kind",
        "bible": "tobias-lind",
        "style": "warm, plain, unhurried, exact about what is right and what is not",
        "background": "15 years as a backend developer, five years teaching adults who change "
        "career into software",
    },
}
# base_url, api_key_env, note shown in the wizard. Model names change often, so the wizard
# asks for them instead of guessing; docs/PROVIDERS.md lists where to look them up.
PROVIDERS: dict[str, dict[str, str]] = {
    "claude-cli": {
        "note": "the Claude Code CLI on your own Claude subscription, no API key",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "note": "free and local; needs Ollama running and a model pulled",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "api_key_env": "GROQ_API_KEY",
        "note": "hosted, has a free tier",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
        "note": "hosted, one key for many models",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "note": "hosted",
    },
    "custom": {
        "api_key_env": "LLM_API_KEY",
        "note": "any other OpenAI-compatible /chat/completions endpoint",
    },
    "none": {
        "note": "no model: built-in starter tickets and fact-only reviews (tests + ruff)",
    },
}


def _q(text: object) -> str:
    """A TOML basic string. JSON string escaping is a subset of TOML's."""
    return json.dumps(str(text), ensure_ascii=False)


def prefix_from(company: str) -> str:
    letters = "".join(ch for ch in company.upper() if ch.isalpha())
    return (letters[:3] or "TKT").ljust(3, "X")


def lane_toml(lane: str, provider: str, model: str, base_url: str = "") -> str:
    preset = PROVIDERS.get(provider, {})
    lines = [f"[llm.{lane}]"]
    if provider == "none":
        return "\n".join([*lines, 'provider = "none"'])
    if provider == "claude-cli":
        lines += ['provider = "claude-cli"', f"model = {_q(model)}", 'bin = "claude"']
        return "\n".join(lines)
    lines += [
        'provider = "openai-compatible"',
        f"base_url = {_q(base_url or preset.get('base_url', ''))}",
        f"model = {_q(model)}",
    ]
    if preset.get("api_key_env"):
        lines.append(f"api_key_env = {_q(preset['api_key_env'])}")
    return "\n".join(lines)


def render_toml(a: dict) -> str:
    prefix = prefix_from(a["company"])
    return f"""\
# Settings for your simulated workplace, written by `boss setup`. Edit freely; `boss tick`
# reads it on every run. Everything about the company and its people is fiction.
# Secrets (API keys, SMTP passwords) never go here: they live in {ENV_FILE}.

[sim]
# company = a boss and tickets. school = an instructor who explains the why in reviews.
setting = {_q(a["setting"])}
# The curriculum. `boss track list` shows what exists; `boss track new` drafts your own.
track = {_q(a["track"])}
# What you are training to become. Empty = the track's own role.
role = {_q(a["role"])}
# Optional: a markdown checklist you keep elsewhere (- [ ] / - [x]); the boss reads the counts.
progress_file = ""

[company]
name = {_q(a["company"])}
city = {_q(a["city"])}
ticket_prefix = {_q(prefix)}
meeting_prefix = {_q(prefix + "M")}

[boss]
name = {_q(a["boss"])}
title = {_q(a["title"])}
style = {_q(a["style"])}
background = {_q(a["background"])}
# How hard they push: kind | firm | brutal.
intensity = {_q(a["intensity"])}
# Backstory: "" = a generic one, a preset from personas/ (ragnhild-varg, tobias-lind),
# a path to your own markdown file, or "none". `boss persona generate` writes one for you.
bible = {_q(a["bible"])}

[tutor]
# The study-mode helper behind `boss help "question"`: explains and quizzes, never codes.
name = {_q(a["tutor"])}

[learner]
# First name only; the boss never needs more.
name = {_q(a["name"])}
pronouns = {_q(a["pronouns"])}
timezone = {_q(a["timezone"])}
# Hours per week the boss may plan for. Tickets are sized against this.
hours_per_week = {int(a["hours"])}

[paths]
# Every sandbox, inbox file, calendar file and the state database live under root.
# Nothing the boss does may touch a path outside it.
root = {_q(a["root"])}

[rules]
# Reviews explain, they never hand over code. Flip only if you want snippets in reviews.
reviews_may_contain_code = false
max_open_tickets = 1
# No messages between these local hours (24h clock).
quiet_hours = [22, 7]
# Minimum hours between two new tickets.
min_hours_between_tickets = 20

[schedule]
# Weekday numbers: 0 = Monday. Times are local to the learner's timezone.
standup_days = [0, 2, 4]
standup_time = "09:00"
one_on_one_day = 4
one_on_one_time = "14:00"

[llm]
# Hard daily cap on quality-lane calls (tickets, reviews, meetings).
max_quality_calls_per_day = 20

{lane_toml("quality", a["provider"], a["quality_model"], a.get("base_url", ""))}

{lane_toml("cheap", a["provider"], a["cheap_model"], a.get("base_url", ""))}

[channels]
inbox = true            # markdown files under <root>/inbox, always on
desktop = false         # notify-send, when installed
ntfy = false            # phone pushes through ntfy; set ntfy_topic to a long random string
ntfy_server = "https://ntfy.sh"
ntfy_topic = ""
email = false           # needs SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM, SMTP_TO
# A push is anything that leaves the inbox. At most this many a day, on these weekdays.
max_pushes_per_day = 2
push_days = [0, 1, 2, 3, 4]

[desk]
# `boss desk` serves a local web page at http://127.0.0.1:<port>/desk/ with your ticket,
# a thread with the boss, a thread with the tutor, standups and notes.
enabled = true
port = 8110

[web]
# Advanced, off by default: rsync the rendered site to your own server. See docs/SELF-HOSTING.md.
enabled = false
host = ""
webroot = ""
url = ""

[corpus]
# Optional: folders of your own study notes or transcripts (.md/.txt). When set, tickets and
# reviews point at your real material by title instead of naming nothing.
enabled = false
dirs = []

[backup]
# Daily copy of the state database and the text record, 14 kept.
local_dir = {_q(a["root"].rstrip("/") + "-backup")}
offsite = false
"""


def _ask(prompt: str, default: str, ask: Callable[[str], str]) -> str:
    shown = f" [{default}]" if default else ""
    answer = ask(f"{prompt}{shown}: ").strip()
    return answer or default


def _choose(prompt: str, options: dict[str, str], default: str, ask: Callable[[str], str]) -> str:
    print(f"\n{prompt}")
    keys = list(options)
    for i, key in enumerate(keys, 1):
        print(f"  {i}. {key}: {options[key]}")
    while True:
        answer = ask(f"Choose 1-{len(keys)} or a name [{default}]: ").strip() or default
        if answer.isdigit() and 1 <= int(answer) <= len(keys):
            return keys[int(answer) - 1]
        if answer in options:
            return answer
        print(f"  not one of: {', '.join(keys)}")


def local_timezone() -> str:
    try:
        link = Path("/etc/localtime").resolve()
        parts = link.parts
        if "zoneinfo" in parts:
            name = "/".join(parts[parts.index("zoneinfo") + 1 :])
            ZoneInfo(name)
            return name
    except (OSError, ZoneInfoNotFoundError, ValueError):
        pass
    return "UTC"


def clean_name(value: str) -> str:
    """Names land inside generated test files and TOML, so quotes and backslashes go."""
    return " ".join(value.replace('"', "").replace("\\", "").replace("$", "").split())


def collect(args: argparse.Namespace, ask: Callable[[str], str] = input) -> dict:
    """Flags win, then (unless --yes) a question, then the default."""
    interactive = not args.yes

    def value(flag: str, prompt: str, default: str) -> str:
        given = getattr(args, flag, None)
        if given:
            return str(given)
        return _ask(prompt, default, ask) if interactive else default

    if interactive:
        print("Setting up your simulated workplace. Press Enter to accept a [default].")
    setting = args.setting or (
        _choose("What kind of place is it?", SETTINGS, "company", ask) if interactive else "company"
    )
    d = DEFAULTS[setting]
    a: dict = {"setting": setting}
    a["company"] = clean_name(value("company", "Name of the " + setting, d["company"]))
    a["city"] = clean_name(value("city", "City it is in", d["city"]))
    boss_word = "boss" if setting == "company" else "instructor"
    a["boss"] = clean_name(value("boss", f"Name of your {boss_word}", d["boss"]))
    is_preset = a["boss"] == d["boss"]
    a["title"] = clean_name(value("title", "Their title", d["title"]))
    intensity = args.intensity or (
        _choose(
            "How hard should they push?",
            {
                "kind": "patient, names what went right first",
                "firm": "direct and demanding, explains the why once",
                "brutal": "expects excellence and says so",
            },
            d["intensity"],
            ask,
        )
        if interactive
        else d["intensity"]
    )
    a["intensity"] = intensity if intensity in INTENSITIES else "firm"
    a["style"], a["background"] = d["style"], d["background"]
    a["bible"] = d["bible"] if is_preset else ""
    a["tutor"] = clean_name(value("tutor", "Name of the study-mode tutor", "Mimir"))
    a["name"] = clean_name(
        value("name", "Your first name", getpass.getuser().split(".")[0].title())
    )
    a["pronouns"] = value("pronouns", "Your pronouns", "they/them")
    tz = value("timezone", "Your timezone", local_timezone())
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        print(f"  unknown timezone {tz!r}, using UTC")
        tz = "UTC"
    a["timezone"] = tz
    hours = value("hours", "Hours a week you can give this", "7")
    a["hours"] = int(hours) if hours.isdigit() and 1 <= int(hours) <= 60 else 7
    root = str(Path(value("root", "Folder for sandboxes and state", "~/fenrir")).expanduser())
    a["root"] = root
    known = tracks.available(Path(root))
    summaries = {k: tracks.load_file(p).summary for k, p in known.items()}
    track = args.track or (
        _choose("Which track?", summaries, tracks.DEFAULT_TRACK, ask)
        if interactive
        else tracks.DEFAULT_TRACK
    )
    if track not in known and not Path(track).expanduser().exists():
        raise SystemExit(f"unknown track {track!r}; available: {', '.join(known)}")
    a["track"] = track
    a["role"] = value("role", "The role you are training for (Enter = the track's own)", "")
    provider = args.provider or (
        _choose(
            "Which model runs the boss?",
            {k: v["note"] for k, v in PROVIDERS.items()},
            "claude-cli",
            ask,
        )
        if interactive
        else "claude-cli"
    )
    if provider not in PROVIDERS:
        raise SystemExit(f"unknown provider {provider!r}; one of: {', '.join(PROVIDERS)}")
    a["provider"] = provider
    a["quality_model"] = a["cheap_model"] = a["base_url"] = ""
    if provider == "claude-cli":
        a["quality_model"] = value("quality_model", "Model for tickets and reviews", "sonnet")
        a["cheap_model"] = value("cheap_model", "Model for nudges and small replies", "haiku")
    elif provider != "none":
        if provider == "custom":
            a["base_url"] = value("base_url", "Base URL ending in /v1", "")
        hint = "the exact model id from your provider's model list"
        a["quality_model"] = value("quality_model", f"Model for tickets and reviews ({hint})", "")
        a["cheap_model"] = value(
            "cheap_model", "Model for nudges and small replies", a["quality_model"]
        )
        if not a["quality_model"]:
            print(
                "  no model given: the lanes are written with an empty model; fill in "
                "[llm.quality] model before the first tick, or the boss uses built-in tickets."
            )
    return a


def write_secret(name: str, secret: str, env_file: Path = ENV_FILE) -> None:
    env_file.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if env_file.exists():
        lines = [
            ln
            for ln in env_file.read_text(encoding="utf-8").splitlines()
            if not ln.startswith(f"{name}=")
        ]
    lines.append(f"{name}={secret}")
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    env_file.chmod(0o600)


def run(args: argparse.Namespace) -> int:
    target = Path(args.config).expanduser() if args.config else CONFIG_DIR / "boss.toml"
    if target.exists() and not args.force:
        print(f"{target} exists. Edit it, or rerun with --force to overwrite.", file=sys.stderr)
        return 1
    answers = collect(args)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_toml(answers), encoding="utf-8")
    print(f"\nwrote {target}")
    key_name = PROVIDERS[answers["provider"]].get("api_key_env")
    if key_name and not args.yes:
        secret = getpass.getpass(f"{key_name} (hidden; Enter to skip and add it later): ").strip()
        if secret:
            write_secret(key_name, secret)
            print(f"saved {key_name} to {ENV_FILE} (mode 600)")
    if key_name:
        print(f"The key lives in {ENV_FILE} as {key_name}=...  (never in boss.toml)")
    print("Next: `boss doctor --llm`, then `boss init` for your first day.")
    return 0
