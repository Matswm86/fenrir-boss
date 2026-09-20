Below is the transcript of a $meeting_type ($meeting_id) for ticket $ticket_id. Write the minutes as $boss_name reading the transcript afterwards. Return ONLY one JSON object.

Transcript:
$transcript

{"minutes_md": "markdown: 5 to 12 bullets: decisions, actions with owner, blockers, facts learned",
 "gate_passed": null,
 "notes_for_boss": "one paragraph: what this tells you about their level",
 "follow_up_hint": "one sentence for the next ticket, or null"}
gate_passed is true or false only when the meeting included the gate probe; otherwise null.
