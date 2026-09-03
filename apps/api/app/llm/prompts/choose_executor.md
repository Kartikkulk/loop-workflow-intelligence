Choose the runtime that should execute this automation.

Workflow: {{name}}
Steps, in order:
{{steps}}

Systems this automation touches: {{connectors}}
Steps needing a system with no usable API: {{no_api_steps}}
Steps that are local file or document work: {{local_steps}}
Steps that map to an existing n8n node: {{n8n_steps}}

The three runtimes, and what each is actually good for:

- `n8n` — has hundreds of maintained SaaS connectors and handles OAuth and
  credential storage. Best when every step is an API call against a system n8n
  already supports and the flow is a straight trigger-to-action chain.
- `playwright` — drives a real browser. The only option when a step touches a
  system with no usable API, because clicking the UI is the only way in. Slower
  and more brittle, so it should not be chosen when an API exists.
- `python` — a plain script. Best when the work is local file handling, parsing
  documents, or computation that a node graph would express awkwardly. Needs no
  credentials for local work and is the easiest to test.

Pick the one that would actually run this workflow most reliably. Return
`method`, one sentence of `rationale` naming the deciding factor, and a
`confidence` between 0 and 1.

Two mistakes to avoid, because they are the common ones:

- Do not pick `n8n` for work that is entirely local. n8n's value is its SaaS
  connectors and its credential handling; choosing it to read a file and parse a
  document means standing up a service to do what a twenty-line script does, and
  it still needs that machine's filesystem mounted into the container.
- Do not pick `playwright` when the systems involved have APIs. Driving a UI is
  the fallback for when there is no other way in, not a default.

Your `rationale` must agree with your `method`. If you find yourself writing
that the steps need no external APIs, the answer is not `n8n`.
