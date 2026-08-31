An automation has repeatedly escalated to a human, and the human has made a
consistent decision each time. Propose a branch rule that captures it.

Automation: {{automation_name}}
Escalations observed: {{count}}

Cases (input features, then what the human decided):
{{cases}}

Return a `condition` as a simple boolean expression over the input feature names
(e.g. `amount > 1000000`, `currency != "INR"`), the `action` to take when it
matches, and one sentence of `rationale`. The condition must be checkable from
the input features alone — do not reference anything not listed above.
