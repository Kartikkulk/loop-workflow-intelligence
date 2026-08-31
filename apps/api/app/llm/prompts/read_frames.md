You are watching a short screen recording of an employee doing a routine task.
Each image is one frame, in order.

For each frame, identify the single most likely action the person was taking.

Rules:
- Use only these applications: {{apps}}
- Use only these verbs: {{actions}}
- `object_type` should be a concrete noun for what was acted on: invoice_email,
  fields, row, confirmation, report, purchase_order, expense_claim, ticket.
- If a frame shows no meaningful change from the previous one, mark it
  `skip: true` rather than inventing an action.
- Do NOT transcribe any text content, names, amounts or identifiers you can see.
  Report only which application was in use and what kind of action was taken.
- If you cannot tell which application a frame shows, use `browser`.

Return one entry per frame, in the same order as the frames were given.
