"""Sales — inbound lead into the CRM.

Owner: Vijay          STATUS: template — replace with what you find

This is a working starting point so you are not editing a blank file, not a
researched finding. Replace the tools, the people and the steps with the real
ones once you have looked at how the team actually works.

What to change:
  1. `tools`  — which applications this team really lives in.
  2. `steps`  — the actions you actually observe, in the order they happen.
  3. `per_person_per_week` and `people` — real frequency, real headcount.
  4. `is_template=False` once it reflects reality.

Keep it to ONE workflow. A domain with one clearly-understood workflow is more
convincing than a domain with five half-understood ones.
"""

from app.domains.base import DomainPack, Step

DOMAIN = DomainPack(
    key="sales",
    label="Sales",
    owner="Vijay",
    summary="An inbound enquiry is qualified and copied into the CRM by hand.",
    tools=["gmail", "crm", "sheets"],
    team="sales",
    people=["u_rohit", "u_neha", "u_imran", "u_divya"],

    workflow_name="Inbound lead to CRM record",
    per_person_per_week=9.0,
    steps=[
        Step("gmail", "read", "enquiry_email", 50, fields=["sender", "subject"]),
        Step("crm", "search", "existing_contact", 55, fields=["customer"]),
        Step("crm", "create", "lead_record", 95, fields=["customer", "amount"]),
        # Optional: not every lead gets logged in the shared pipeline sheet.
        Step("sheets", "update", "pipeline_tracker", 45, probability=0.4, fields=["customer"]),
        Step("gmail", "send", "acknowledgement", 40, fields=["recipient"]),
    ],

    reorder_probability=0.08,
    context_switch_probability=0.40,
    anomaly_probability=0.03,
    is_template=True,
)
