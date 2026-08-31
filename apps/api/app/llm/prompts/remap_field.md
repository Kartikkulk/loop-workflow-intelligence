An automation step has broken. A field it depends on no longer resolves.

Automation: {{automation_name}}
Step: {{step_id}} ({{step_type}} via {{connector}})
Field that no longer resolves: "{{missing_field}}"

The schema as it exists now:
{{current_schema}}

The schema this step was built against:
{{original_schema}}

Propose the single most likely remapping of the missing field to a field that
exists now. Score your confidence 0-1. Be conservative: a wrong remapping on a
step that writes to a ledger is worse than asking a human. If nothing is a
plausible match, return confidence below 0.5 and say so in `rationale`.
