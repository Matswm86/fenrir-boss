# Model providers

`boss.toml` has two lanes. `quality` writes tickets, reviews and meetings. `cheap` writes
nudges and small replies. If only one lane is configured, it serves both.

```toml
[llm]
max_quality_calls_per_day = 20

[llm.quality]
provider = "openai-compatible"
base_url = "http://localhost:11434/v1"
model = "<model id>"
# api_key_env = "GROQ_API_KEY"      # name of the secret in ~/.config/fenrir-boss/boss.env
# fallback_model = "<model id>"     # tried once when the first model fails
# timeout_s = 240
# max_tokens = 8000
# temperature = 0.4

[llm.cheap]
provider = "none"
```

## claude-cli

```toml
[llm.quality]
provider = "claude-cli"
model = "sonnet"
bin = "claude"
```

Runs `claude -p` with every tool disallowed, on whatever Claude subscription the CLI is signed
in to. No API key. `model` is whatever the CLI's `--model` flag accepts.

## openai-compatible

Any server that speaks `POST {base_url}/chat/completions`. `boss setup` knows these base URLs:

| Preset | base_url | Secret |
|---|---|---|
| ollama | `http://localhost:11434/v1` | none |
| groq | `https://api.groq.com/openai/v1` | `GROQ_API_KEY` |
| openrouter | `https://openrouter.ai/api/v1` | `OPENROUTER_API_KEY` |
| openai | `https://api.openai.com/v1` | `OPENAI_API_KEY` |
| custom | you type it | `LLM_API_KEY` |

Model ids change often, so setup asks for them instead of guessing: use the exact id from
your provider's model list (`ollama list` for Ollama).

Secrets go in `~/.config/fenrir-boss/boss.env`, one `NAME=value` per line, mode 600. A process
environment variable of the same name wins over the file.

## none

No model. Levels with a built-in seed still hand out that ticket, and `boss submit` still runs
the tests and ruff and gives a fact-only verdict. Meetings, the tutor and generated tickets
need a model.

## What to expect from small models

Ticket writing needs one long, valid JSON object containing code that parses, tests that fail
on the stubs, and stubs with no logic. The validator rejects a malformed object and retries once
with the reason; a ticket whose tests already pass on the stubs is discarded without a retry.
A model that cannot do that gets the level's built-in seed where there is one and produces no
ticket where there is not; `boss doctor --llm` only proves the lane answers, not that it can
write tickets. Try `boss tick --force` and read the result.
