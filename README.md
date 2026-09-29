# fenrir-boss

A simulated workplace that trains you. You get a boss (or an instructor), a company, fictional
clients and a ladder of levels. The boss hands you one small paid job at a time, as a real git
repository with failing tests. You type every line. The boss reviews what you hand in, holds
standups and a weekly 1:1, and decides when you move up a level.

The one rule the whole thing is built around: **the boss never writes your code.** Not a line.
Reviews point at file and line and ask questions; a separate study-mode tutor explains concepts
and quizzes you, and does not write your code either. Reviews, and answers on the desk, in
`boss help` and in `boss ask`, also pass through a code stripper, so the rule holds there even
when a model forgets it. In live 1:1s and terminal standups the boss's prompt is the only guard.

You choose the company name, the boss's name and temperament, your own name, and the career
you are training for. Everything about the company and its people is fiction.

```
$ boss status
Northwind Academy: Alex reports to Tobias Lind
Track: Python foundations (python-foundations)
Level: L1 Values and decisions (weeks 1 to 3); next level: 0/5 tickets accepted at L1
Open tickets:
  NOR-0002 Trip fee calculator with member and volunteer discounts [Ridgeway Hiking Club] open, due Wed 23 Sep 17:00
Next meetings:
  NORM-0001 Standup Mon 21 Sep 09:00
  NORM-0004 1:1 Fri 25 Sep 14:00
```

## Who it is for

- **Learning Python from zero.** The `python-foundations` track starts at "what is a variable"
  and ends with a capstone you scope with a client.
- **Becoming an AI engineer.** The `ai-engineer` track goes from Python by hand through APIs,
  RAG with evals, agents and MCP, LLMOps, to scoping and pricing client work.
- **Becoming a software engineer.** The `software-engineer` track covers tests and design, SQL,
  HTTP APIs, CI and containers, debugging legacy code, design documents and code review.
- **Anything else.** `boss track new --role "data analyst at a hospital"` has the model draft a
  full track (levels, clients, an internal project) that you then read and edit. It is a plain
  data file.

## Quick start

Requirements: Python 3.12 or newer, `git`, and [`uv`](https://docs.astral.sh/uv/) (the ticket
sandboxes use it). The tool itself has no dependencies beyond the standard library.

```bash
git clone https://github.com/Matswm86/fenrir-boss.git
cd fenrir-boss
uv tool install .            # puts `boss` on your PATH; or skip this and run ./bin/boss

boss setup                   # names, setting, track, model; writes ~/.config/fenrir-boss/boss.toml
boss doctor --llm            # checks tools and pings the model
boss init                    # your first day: handbook, calendar, first ticket
boss status
```

Then work the ticket it names: open the folder, `uv sync`, `uv run pytest -q`, read the failing
test, write the code, commit, and hand it in:

```bash
boss submit NOR-0001 -m "what the traceback said, and what confused me"
```

`boss setup --yes` accepts every default (company FENRIR AI, boss Ragnhild Varg, the Python
foundations track). Every question is also a flag, so it scripts:

```bash
boss setup --yes --setting school --company "Northwind Academy" --boss "Tobias Lind" \
  --name Alex --track software-engineer --provider ollama --quality-model "<model id>"
```

## Company or school

`boss setup` asks which kind of place it is.

- **company**: a manager who holds a professional standard. Reviews say what is wrong and ask a
  question. Temperament is a knob: `kind`, `firm` or `brutal`.
- **school**: an instructor who sets the same tickets and, in reviews, explains the why behind
  each point in a sentence or two, after you have tried, never before.

Both keep the rule. Two ready-made characters ship as examples (`ragnhild-varg`, `tobias-lind`);
name your own boss and `boss persona generate` writes a backstory for them.

## Which model runs it

Two lanes, each pointing at any provider (see [docs/PROVIDERS.md](docs/PROVIDERS.md)):

| Provider | Needs | Notes |
|---|---|---|
| `claude-cli` | the Claude Code CLI, signed in | uses your own Claude subscription, no API key |
| `ollama` | Ollama running locally, a model pulled | free and private; quality depends on the model |
| `groq`, `openrouter`, `openai` | an API key in the private env file | hosted |
| `custom` | any OpenAI-compatible `/chat/completions` URL | LM Studio, vLLM, a gateway |
| `none` | nothing | built-in starter tickets and fact-only reviews (tests + ruff) |

Ticket writing is the demanding call: the model must produce a brief, stubs, tests that fail on
the stubs, and data files as one valid JSON object. The tool validates the JSON (every field
present, files that parse, stubs with no logic, a test file and a stub in every code ticket) and
retries once with the reason. It then runs the tests on the stub and throws the ticket away if
they pass. Dependencies off the level's allowlist are dropped, and the ticket says so. Small
local models often fail that validation; when the model errors or its JSON is rejected twice,
levels with a built-in seed fall back to it. Other levels, and a ticket whose tests pass on the
stub, produce no ticket on that tick and the next tick tries again. API keys never go in
`boss.toml`; they live in `~/.config/fenrir-boss/boss.env` (mode 600).

## Day to day

| Command | What it does |
|---|---|
| `boss status` | level, open ticket, next meetings, model calls today |
| `boss ticket <id>` | print the brief |
| `boss submit <id> -m "..."` | run tests and ruff, then the review |
| `boss standup` | three lines: yesterday, today, blockers |
| `boss meet <id>` | hold the 1:1 (the gate to the next level) or a client scoping call |
| `boss help "question"` | the tutor: explains and quizzes, never codes |
| `boss ask "question"` | the boss: what the ticket asks and what gets checked |
| `boss desk` | a local web page (ticket, boss and tutor threads, standups, inbox, ladder) at `http://127.0.0.1:8110/desk/` |
| `boss ladder` | the levels and where you are |
| `boss track list / show / check / new` | curricula |
| `boss tick` | the scheduler: new tickets, meeting invites, late nudges |
| `boss install-timer` | run the tick every 15 minutes (Linux, systemd user timer) |
| `boss notebook` | the boss's private notes about you; it is your sandbox, you may read them |

Without the timer, run `boss tick` yourself whenever you sit down. It respects quiet hours, a
minimum gap between tickets, and one open ticket at a time.

Write `/ooc` in any conversation with the boss and the simulation answers out of character. If
you sincerely ask whether the boss is an AI, it says so.

## What it will and will not do

- It stays inside one folder (`[paths] root`). Sandboxes, inbox, calendar files and the SQLite
  state all live there; paths from the model are checked before anything is written. The one
  exception is the daily backup, which goes to `[backup] local_dir` (by default `<root>-backup`,
  14 days kept).
- Notifications are off by default. The inbox is markdown files. Desktop, ntfy and email
  pushes are opt-in in `boss.toml`, capped at two a day on weekdays.
- Ticket sandboxes are Python (pytest + ruff through `uv`). Tracks for other roles use Python
  for the programmable parts and document tickets for the rest. Other languages would need a
  new sandbox runner; pull requests welcome.
- It is a practice environment, not a credential and not a course. The clients, budgets and
  people are invented, and a model can still be wrong in a review. The tests and ruff results
  in a review are facts; the prose around them is a model's opinion.

## Make it yours

- **Tracks**: [docs/TRACKS.md](docs/TRACKS.md). One TOML or JSON file holds levels, clients and
  an internal project series.
- **Characters**: a markdown backstory in `src/boss/personas/`, or your own file via
  `[boss] bible`.
- **Your study material**: set `[corpus] enabled = true` and list folders of notes (`.md`,
  `.txt`) or transcripts in `[corpus] dirs`, each with a `name` and a `path`, and tickets and
  reviews name your real material by title.
- **Self-hosting the desk**: [docs/SELF-HOSTING.md](docs/SELF-HOSTING.md). Read the warning
  there first.

## Development

```bash
uv sync --group dev
uv run pytest -q          # offline, no model calls
uv run ruff check . && uv run ruff format --check .
boss eval --replay        # voice and no-code checks over what the boss already sent
```

MIT licensed. Any resemblance of the fictional companies and people to real ones is accidental.
