# Tracks

A track is one file: the level ladder, the fictional clients, and an optional internal project
series. Built-in tracks are in `src/boss/tracks/`. Your own go in `<root>/tracks/` as `.toml`
or `.json`, or anywhere on disk if `[sim] track` in `boss.toml` is a path.

```bash
boss track list                 # what exists, which one is active
boss track show ai-engineer     # levels, competencies, clients
boss track check my-track       # validate a file you edited
boss track new --role "data engineer at a logistics firm" --notes "I know SQL, no Python"
```

`track new` asks the quality-lane model for a draft, validates it, and saves JSON under
`<root>/tracks/`. Nothing is activated until you set `[sim] track`. Read the draft: a model can
name a package that does not exist, and the package allowlist is what tickets may depend on.

## Shape

```toml
[track]
key = "my-track"
name = "My track"
summary = "One sentence."
role = "what the learner is training to become"
common_packages = ["pytest", "ruff"]      # allowed at every level

[[levels]]                                 # level 0, always onboarding
name = "Onboarding"
phase = "day zero"
competencies = ["..."]                     # observable skills; a ticket trains one or two
shapes = ["..."]                           # kinds of small job that fit this level
packages = []                              # third-party PyPI names a ticket may depend on
required_accepted = 1                      # approved tickets needed before the gate 1:1
estimate_hours = "1"
gate_questions = ["...", "...", "..."]     # asked aloud in the 1:1 before promotion
extra_rules = "Sentences the ticket writer must obey at this level."
seed = "onboarding"                        # optional: a built-in ticket used without a model
# kind = "doc"                             # for levels that issue document tickets

[[clients]]                                # optional; omit all for the default pool
name = "Invented Ltd"
sector = "..."
contact = "First Last"
role = "owner"
data = "what files and exports they have"
situation = "what hurts, in their words"
hidden = ["budget", "real deadline", "a data problem", "a constraint"]

[[series]]                                 # optional
key = "toolkit"
name = "toolkit: one line"
levels = [2, 4]                            # first and last level it runs at
goal = "..."
constraints = ["..."]
milestones = ["one ticket each", "..."]
```

Levels are numbered by their order in the file. Level 0 is onboarding by convention
(terminal, git, uv, reading a traceback). Built-in seeds: `onboarding`, `price-labels`
(first functions and if/else), `sales-summary` (CSV, dicts, a small CLI). A level with a seed
still gets model-written tickets when a model is available; the seed is the fallback, and
level 0 always uses it.

Hidden client facts only come out when the learner asks the right question in a scoping call
(`boss meet <id>`), which is the point of the call.

## Switching track

Edit `[sim] track`. Your level number carries over, which is rarely what you want on a
different ladder: `boss admin-level 0 --reason "new track"` starts from the bottom.
