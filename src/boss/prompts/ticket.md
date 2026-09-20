Write the next ticket for $engineer_name. Return ONLY one JSON object: no prose before or after, no markdown fence.

Current level: L$level "$level_name" ($level_phase).
Competencies this level trains. Pick ONE or TWO for this ticket, never all:
$competencies

Ticket shapes that fit this level:
$shapes

Client for this ticket:
$client_block

Recent tickets. Do not repeat a shape or a client problem already used:
$history

What they have ticked off in their own study tracker:
$progress_hints

$reviewer_hint

Study material retrieved for the competencies above. When there is any, anchor the ticket to it: name one source by its exact title in the brief ("go through X before you start") and take the problem shape from what it teaches. Never invent titles; when nothing was retrieved, name no source at all.
$corpus_block

$standards

Rules for the ticket:
- Finishable in $estimate_hours hours by someone at this level who types every line themselves.
- "brief" is your message to $engineer_name, in your voice, to someone training as: $role. It covers: the client, why they need it, what done looks like, what you will check. Markdown. It must NOT contain Python code. Plain-English steps are fine.
- You provide the acceptance tests under tests/. That is your job as reviewer. Tests import from the module under src/ that the brief names (the sandbox puts src/ on the import path, so `from module import name`), are deterministic, and must FAIL against the stub you provide.
- Stub files under src/ contain only: a module docstring, the imports they may use, and function signatures with a docstring and `raise NotImplementedError`. No logic. $engineer_name writes the logic.
- Put realistic small data files (CSV, JSON, text) under data/ when the ticket needs them. No real companies, no real people.
- Dependencies only from this allowlist, and only when needed: $packages
- "boss_notes" is for the reviewer only and is never shown to $engineer_name: what a good solution looks like, two common mistakes, what to probe.
- 3 to 6 measurable acceptance criteria.
- Today is $today. due_days between 2 and 5.
- $extra_rules

JSON keys, all required (meeting is null when there is none):
{"title": "short imperative title",
 "slug": "kebab-case-slug",
 "client": "$client_name",
 "kind": "$kind",
 "estimate_hours": 2,
 "due_days": 3,
 "brief": "markdown message to $engineer_name",
 "acceptance": ["...", "..."],
 "learning_goals": ["...", "..."],
 "dependencies": [],
 "files": {"src/module.py": "...", "tests/test_module.py": "...", "data/file.csv": "..."},
 "run_command": "uv run pytest -q",
 "boss_notes": "reviewer-only notes",
 "meeting": null}
For kind "doc": files are markdown templates, run_command is null, and meeting is {"type": "client_call", "in_days": 1, "agenda": "..."}.
