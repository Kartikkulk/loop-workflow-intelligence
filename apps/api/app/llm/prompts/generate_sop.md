Write a Standard Operating Procedure in Markdown for this repetitive workflow,
suitable for handing to a new employee on their first day.

Workflow: {{name}}
Observed steps: {{signature}}
Performed by {{distinct_users}} employees, {{instance_count}} times in the
observation window. Median duration {{median_minutes}} minutes.
Apps involved: {{apps}}
Automatability: {{automatability}} — {{automatability_note}}

Include these sections, in order, as H2 headings:
Purpose, Trigger, Systems Touched, Procedure (numbered, one line per observed
step, written as an instruction to a person), Known Exceptions, Owner,
Estimated Duration.

Be concrete and imperative. No preamble, no closing commentary — output only
the Markdown document, starting with an H1 of the workflow name.
