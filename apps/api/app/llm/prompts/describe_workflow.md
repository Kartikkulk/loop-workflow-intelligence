You are a workflow analyst. A finance-operations employee has described a
recurring task in their own words. Synthesise a plausible sequence of observable
application events that this task would produce in an activity log.

Employee description:
{{description}}

Rules:
- Use only these apps: {{apps}}
- Use only these actions: {{actions}}
- Between 3 and 9 steps. Each step is one observable user action.
- Realistic durations: reading an email ~20-60s, extracting fields from a PDF
  ~60-180s, appending a spreadsheet row ~30-90s, sending an email ~30-60s.
- object_type should be a concrete noun: invoice_email, fields, row, confirmation,
  report, purchase_order, expense_claim, ticket.
- Infer how many times per week this recurs and how many people likely do it.
