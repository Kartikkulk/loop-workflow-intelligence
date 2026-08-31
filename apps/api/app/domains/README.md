# Adding your domain

One file. One workflow. No changes anywhere else.

## The 5-minute version

1. Copy `sales.py` to `<your_domain>.py`.
2. Change `key`, `label`, `owner`, `summary`.
3. List the `tools` that team actually uses.
4. List the `people` and their `team`.
5. Replace `steps` with the actions you actually observed, in order.
6. Set `is_template=False` when it reflects reality rather than a guess.
7. `make demo` — your domain appears in the console.

That's it. The registry finds your file automatically, so there is no list to
edit and no merge conflict when two of you add a domain on the same day.

## One workflow per domain, deliberately

A domain with one workflow you can explain end to end is worth more than a
domain with five you half-understand. If you find several, pick the one that is
most repetitive and most painful, and get that one right.

## Writing good steps

A `Step` is one **observable** action — something that would show up in a log
or that a browser extension could see. Not "review the invoice"; rather
"open the invoice email", "extract the fields", "add a row to the sheet".

```python
Step("gmail", "read", "invoice_email", 45, fields=["sender", "subject"])
#     app     action  object_type    secs   payload keys this step writes
```

| Argument | Meaning |
|---|---|
| `app` | Which application. Use a canonical one where it fits (`gmail`, `sheets`, `erp`, `outlook`, `slack`, `drive`, `browser`, `pdf`). An unknown app is fine — it registers itself. |
| `action` | One of `read`, `create`, `update`, `delete`, `send`, `extract`, `search`, `navigate`. |
| `object_type` | A concrete noun for what was acted on: `invoice_email`, `lead_record`, `leave_request`. |
| `seconds` | Roughly how long it takes. Real durations vary around this. |
| `probability` | Below `1.0` makes the step optional. Real work has optional steps — include them. |
| `fields` | The payload keys this step writes. These become the automation's inputs and outputs, so be concrete. |

## Making it realistic, which matters more than it sounds

Detection reads structure. If your steps are perfectly uniform, the platform
will report perfect automatability and the finding will be worthless. Real work
varies, so say how it varies:

| Knob | Use it when |
|---|---|
| `probability` on a step | Someone only does this step sometimes |
| `reorder_probability` | Two adjacent steps sometimes swap |
| `context_switch_probability` | People get pulled into another app mid-task — this is what the Interruption Tax measures |
| `anomaly_probability` | Genuine one-offs happen |
| `freeform=True` | **The order genuinely differs every time.** See `customer_support.py` |

`freeform` is the important one. If your domain's work is judgement-heavy and
the order really does change every time, set it — and the platform will
correctly tell you **not** to automate it. That is a finding, not a failure. It
is arguably the most interesting thing the platform does.

## What you must not change

Anything outside this directory. In particular:

- `app/services/` — clustering, scoring, the engine, the trust ladder
- `app/api/` — the routes
- `app/llm/` — the prompts and tool schemas

If your domain needs something the core cannot do, **open an issue** rather than
editing core. That is what keeps five people mergeable.

## Checking your work

```bash
make demo     # reseed with your domain included
make dev      # console on :3000 — your domain should appear on Discovery
make test     # the detection tests must stay green
```

If your workflow does not appear, the usual cause is too few instances:
detection needs **at least 15** before it treats a pattern as an opportunity.
Raise `per_person_per_week` or add people.
