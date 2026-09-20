Design a training track for a simulated workplace. The learner wants to become: $role.
$notes

A track is a ladder of levels. At each level a fictional boss hands the learner small paid jobs ("tickets") for fictional clients. A code ticket is a Python sandbox: stub functions under src/, the boss's pytest tests under tests/, small data files under data/. A doc ticket is a markdown template to fill in (a plan, a statement of work, a review), sometimes after a simulated client call. The learner types every line; the boss never writes their code. So every level must be trainable through Python code tickets or written documents. For a role that is not mainly programming, use Python for the parts that are (data handling, automation, analysis, calculation) and doc tickets for the rest.

Return ONLY one JSON object, no prose, no markdown fence, in exactly this shape:
{"track": {"key": "kebab-case-key", "name": "Short name", "summary": "one sentence", "role": "$role", "common_packages": ["pytest", "ruff"]},
 "levels": [
   {"name": "Onboarding", "phase": "day zero", "kind": "code", "seed": "onboarding",
    "competencies": ["..."], "shapes": ["..."], "packages": [],
    "required_accepted": 1, "estimate_hours": "1", "gate_questions": ["...", "...", "..."],
    "extra_rules": "..."}
 ],
 "clients": [
   {"name": "...", "sector": "...", "contact": "First Last", "role": "owner",
    "data": "what files and exports they have", "situation": "what hurts, in their words",
    "hidden": ["budget", "real deadline", "a data problem", "a constraint they will only mention if asked"]}
 ],
 "series": [
   {"key": "kebab", "name": "name: one line", "levels": [2, 4], "goal": "...",
    "constraints": ["..."], "milestones": ["...", "..."]}
 ]}

Rules:
- 6 to 8 levels. Level 0 is always the onboarding level exactly as in the shape above (terminal, git, uv, virtual environment, reading a traceback, a gitignored env file), with "seed": "onboarding". Only level 0 has a "seed" key.
- Level 1 assumes no programming experience unless the notes above say otherwise. Difficulty rises steadily; the last level is the work a senior person in this role does, usually "kind": "doc".
- Each level: 5 to 10 concrete competencies (things a person can be observed doing), 3 to 5 ticket shapes (kinds of small job, finishable in the estimate), 3 gate questions the boss asks aloud before promotion (they test understanding, not recall), "required_accepted" between 3 and 6, "estimate_hours" like "1 to 2".
- "packages" is the allowlist of third-party PyPI package names a ticket at that level may depend on, cumulative as levels rise. Only real, widely used packages you are certain exist. When unsure, leave it out. Early levels: empty (standard library only).
- "extra_rules": one or two sentences the ticket writer must obey at that level (for example: tests never touch the network). For doc levels say: kind is "doc", files are markdown templates with headings and one-line hints only, run_command is null.
- 5 or 6 fictional clients that fit this role's industry. Invented names only: no real companies, no real people. Each has 4 hidden facts. Small organisations with concrete, mundane problems.
- 1 internal project series: a small library or tool the company builds for itself over 5 to 8 milestones, each milestone one ticket, spanning the middle levels.
- Plain English. Never an em dash. No marketing language.
