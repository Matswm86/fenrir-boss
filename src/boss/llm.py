"""Two lanes, any provider. quality: tickets, reviews, meetings. cheap: nudges and small talk.

Each lane in boss.toml names a provider:
- "claude-cli": the Claude Code CLI (`claude -p`) on the user's own subscription, no API key.
- "openai-compatible": any /chat/completions endpoint: Ollama on localhost, Groq, OpenRouter,
  OpenAI, LM Studio, vLLM. `base_url`, `model`, and `api_key_env` naming the secret.
- "none": the lane is off.

Every call is logged to the state database with lane, model, seconds and cost, so
`boss status` can show what the boss used today. Stdlib only.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from uuid import uuid4

from boss.config import Config
from boss.state import State

NO_TOOLS_PREFACE = (
    "You have NO TOOLS available. Do not attempt any tool invocation: no Read, no Bash, "
    "no WebFetch, nothing. All inputs are in the user message. Produce ONLY the requested "
    "text. If a value you need is missing, write <unspecified> instead of looking it up.\n\n"
)
# Some API gateways answer 403 to urllib's default agent string.
USER_AGENT = "fenrir-boss/0.2"
THINK_RE = re.compile(r"<think>.*?</think>", re.S)
LANES = ("quality", "cheap")


@dataclass
class Reply:
    text: str
    lane: str
    model: str
    seconds: float
    cost_usd: float = 0.0
    session_id: str | None = None
    ok: bool = True
    error: str = ""


def lane_options(cfg: Config, lane: str) -> dict:
    """`[llm.<lane>]` from boss.toml. A missing lane is provider "none"."""
    opts = dict(cfg.section("llm").get(lane) or {})
    opts.setdefault("provider", "none")
    return opts


class LLM:
    def __init__(self, cfg: Config, state: State):
        self.cfg = cfg
        self.state = state
        self.opts = cfg.section("llm")
        self._sessions: dict[str, list[dict]] = {}

    def available(self, lane: str | None = None) -> bool:
        lanes = (lane,) if lane else LANES
        return any(lane_options(self.cfg, name)["provider"] != "none" for name in lanes)

    # --- lanes --------------------------------------------------------------------
    def quality(
        self,
        system: str,
        user: str,
        *,
        purpose: str,
        session_id: str | None = None,
        persist: bool = False,
        timeout: int | None = None,
        model_override: str | None = None,
    ) -> Reply:
        opts = lane_options(self.cfg, "quality")
        if opts["provider"] == "none":
            # One lane configured is a supported setup: the other lane stands in.
            opts = lane_options(self.cfg, "cheap")
        model = model_override or str(opts.get("model", ""))
        cap = int(self.opts.get("max_quality_calls_per_day", 20))
        if self.state.quality_calls_today() >= cap:
            return Reply("", "quality", model, 0.0, ok=False, error=f"daily cap of {cap} reached")
        reply = self._call(
            "quality",
            opts,
            model,
            system,
            user,
            purpose=purpose,
            session_id=session_id,
            persist=persist,
            timeout=timeout,
            max_tokens=int(opts.get("max_tokens", 8000)),
        )
        fallback = opts.get("fallback_model")
        if not reply.ok and fallback and fallback != model and model_override is None:
            return self.quality(
                system,
                user,
                purpose=f"{purpose} (fallback)",
                session_id=session_id,
                persist=persist,
                timeout=timeout,
                model_override=str(fallback),
            )
        return reply

    def cheap(
        self,
        system: str,
        user: str,
        *,
        purpose: str,
        max_tokens: int = 700,
        model: str | None = None,
    ) -> Reply:
        opts = lane_options(self.cfg, "cheap")
        if opts["provider"] == "none":
            return Reply("", "cheap", "", 0.0, ok=False, error="cheap lane is off")
        return self._call(
            "cheap",
            opts,
            model or str(opts.get("model", "")),
            system,
            user,
            purpose=purpose,
            max_tokens=max_tokens,
        )

    def _call(
        self,
        lane: str,
        opts: dict,
        model: str,
        system: str,
        user: str,
        *,
        purpose: str,
        session_id: str | None = None,
        persist: bool = False,
        timeout: int | None = None,
        max_tokens: int = 700,
    ) -> Reply:
        provider = opts["provider"]
        if provider == "claude-cli":
            reply = self._claude_cli(
                lane,
                opts,
                model,
                system,
                user,
                session_id=session_id,
                persist=persist,
                timeout=timeout,
            )
        elif provider == "openai-compatible":
            reply = self._openai_compatible(
                lane,
                opts,
                model,
                system,
                user,
                session_id=session_id,
                persist=persist,
                timeout=timeout,
                max_tokens=max_tokens,
            )
        else:
            return Reply("", lane, model, 0.0, ok=False, error=f"no provider for the {lane} lane")
        self.state.log_llm(
            lane=lane,
            model=reply.model,
            purpose=purpose,
            seconds=reply.seconds,
            cost_usd=reply.cost_usd,
            ok=int(reply.ok),
        )
        return reply

    # --- provider: claude -p -------------------------------------------------------
    def _claude_cli(
        self,
        lane: str,
        opts: dict,
        model: str,
        system: str,
        user: str,
        *,
        session_id: str | None,
        persist: bool,
        timeout: int | None,
    ) -> Reply:
        model = model or "sonnet"
        cmd = [
            str(opts.get("bin", "claude")),
            "-p",
            "--model",
            model,
            "--output-format",
            "json",
            "--max-turns",
            "3",
            "--system-prompt",
            NO_TOOLS_PREFACE + system,
            "--exclude-dynamic-system-prompt-sections",
            "--disallowedTools",
            "*",
        ]
        if session_id:
            cmd += ["--resume", session_id]
        if not persist:
            cmd.append("--no-session-persistence")
        start = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                input=user,
                text=True,
                capture_output=True,
                timeout=timeout or int(opts.get("timeout_s", 240)),
                check=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            secs = time.monotonic() - start
            return Reply("", lane, model, secs, ok=False, error=type(exc).__name__)
        secs = time.monotonic() - start
        try:
            payload = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError:
            payload = {}
        text = str(payload.get("result") or "")
        cost = float(payload.get("total_cost_usd") or 0.0)
        ok = proc.returncode == 0 and not payload.get("is_error") and bool(text.strip())
        if not ok:
            err = (text or proc.stderr or f"exit {proc.returncode}")[:300]
            return Reply(text, lane, model, secs, cost, payload.get("session_id"), False, err)
        return Reply(text, lane, model, secs, cost, payload.get("session_id"))

    # --- provider: any OpenAI-compatible endpoint --------------------------------------
    def _openai_compatible(
        self,
        lane: str,
        opts: dict,
        model: str,
        system: str,
        user: str,
        *,
        session_id: str | None,
        persist: bool,
        timeout: int | None,
        max_tokens: int,
    ) -> Reply:
        base = str(opts.get("base_url", "")).rstrip("/")
        if not base or not model:
            return Reply("", lane, model, 0.0, ok=False, error=f"llm.{lane} needs base_url + model")
        key_name = str(opts.get("api_key_env", "") or "")
        key = (self.cfg.secrets.get(key_name) or os.environ.get(key_name, "")) if key_name else ""
        if key_name and not key:
            return Reply("", lane, model, 0.0, ok=False, error=f"{key_name} not set")
        # A meeting is one process, so the conversation lives in memory under a session id.
        history = self._sessions.get(session_id or "", [])
        messages = [{"role": "system", "content": system}, *history]
        messages.append({"role": "user", "content": user})
        headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        body = json.dumps(
            {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": float(opts.get("temperature", 0.4)),
            }
        ).encode()
        req = urllib.request.Request(f"{base}/chat/completions", data=body, headers=headers)
        start = time.monotonic()
        err = ""
        for attempt in (1, 2):
            try:
                wait = timeout or int(opts.get("timeout_s", 240))
                with urllib.request.urlopen(req, timeout=wait) as resp:
                    data = json.load(resp)
                text = THINK_RE.sub("", data["choices"][0]["message"]["content"] or "").strip()
                secs = time.monotonic() - start
                if not text:
                    return Reply("", lane, model, secs, ok=False, error="empty reply")
                sid = session_id
                if persist:
                    sid = sid or uuid4().hex
                    self._sessions[sid] = [
                        *history,
                        {"role": "user", "content": user},
                        {"role": "assistant", "content": text},
                    ]
                return Reply(text, lane, model, secs, session_id=sid)
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt == 1:
                    time.sleep(min(float(exc.headers.get("Retry-After", "10") or 10), 30))
                    continue
                err = f"HTTP {exc.code}"
                break
            except (
                urllib.error.URLError,
                TimeoutError,
                KeyError,
                IndexError,
                TypeError,
                json.JSONDecodeError,
            ) as exc:
                err = type(exc).__name__
                break
        return Reply("", lane, model, time.monotonic() - start, ok=False, error=err)

    # --- fallback chain -------------------------------------------------------------
    def ask(self, system: str, user: str, *, purpose: str, prefer: str = "quality") -> Reply:
        order = ("quality", "cheap") if prefer == "quality" else ("cheap", "quality")
        last: Reply | None = None
        for lane in order:
            reply = (
                self.quality(system, user, purpose=purpose)
                if lane == "quality"
                else self.cheap(system, user, purpose=purpose)
            )
            if reply.ok:
                return reply
            last = reply
        assert last is not None
        return last


FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.M)


def extract_json(text: str) -> dict:
    """First balanced {...} object in the text, fences tolerated. Raises ValueError."""
    cleaned = FENCE_RE.sub("", text.strip())
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    if start < 0:
        raise ValueError("no JSON object in reply")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                obj = json.loads(cleaned[start : i + 1])
                if not isinstance(obj, dict):
                    raise ValueError("JSON is not an object")
                return obj
    raise ValueError("unbalanced JSON object in reply")
