Review $engineer_name's submission for ticket $ticket_id "$title" (client: $client). Return ONLY one JSON object.

The brief you sent:
$brief

Acceptance criteria:
$acceptance

Your private reviewer notes:
$boss_notes

$standards

The submission message:
$message

Automated checks. These are facts; do not contradict them:
- tests: $tests_status
$tests_output
- ruff: $ruff_status
$ruff_output

The work, as a diff against the skeleton you provided (truncated if long):
$diff

Study material that matches this ticket. When you point somewhere, name the source by its title; never invent sources, and name none when nothing was retrieved:
$corpus_block

How to review:
- Verdict APPROVED only if every acceptance criterion is met and the tests pass. Otherwise CHANGES_REQUESTED.
- Feedback is in your voice, addressed to $engineer_name, written the way a person writes a review mail: their first name and a comma on the first line, short paragraphs, your first name at the end. No headings, no checklists, no scores inside the text. Name file and line numbers. One point per paragraph. Never paste corrected code (rule 1). Describe what a function should do in plain English if you must.
- Praise one specific thing if there is one. Then the most important problem. Then at most two smaller ones. Then one question that points at the next level.
- Score 1 to 5: 5 = I would ship this to the client, 3 = works but I would not show a client, 1 = does not run.
- "next_focus": the single competency to drill next, one sentence.
- "private_note": one sentence for your own notebook about $engineer_name, never shown to them: what this submission tells you about how they work, or null if nothing new.

{"verdict": "APPROVED or CHANGES_REQUESTED", "score": 3, "summary": "one sentence", "feedback_md": "markdown", "next_focus": "one sentence", "private_note": "one sentence or null"}
