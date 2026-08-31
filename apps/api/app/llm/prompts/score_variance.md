Assess how much human judgement this workflow requires.

Workflow: {{name}}
Step sequence: {{signature}}
Sample of the free-text content observed during these tasks:
{{samples}}

Measured structural variance:
- step-order entropy: {{entropy}}
- distinct step-sequence variants: {{variants}}
- parameter value spread: {{spread}}

Return `judgement_ratio` between 0 and 1: the share of this task's outcome that
depends on tone, relationship, negotiation or discretion rather than on rules
that could be written down. A pure data-entry task is 0.0. A task where the
right answer depends on knowing the customer is 1.0.

Also return `build_effort` from 1 to 5, estimating implementation cost from step
count and integration complexity, and one sentence of `reasoning` a finance
manager would find credible.
