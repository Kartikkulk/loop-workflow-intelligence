"""Sales — inbound enquiry to lead tracker.

Owner: Vijay

One repetitive workflow: a salesperson reads a customer enquiry in Gmail,
records the lead in the shared Google Sheet, and sends an acknowledgement.
There is no CRM in this pack. Optional follow-up-date updates and the
generator's existing variance knobs keep instances from being identical.
"""

from app.domains.base import DomainPack, Step

DOMAIN = DomainPack(
    key="sales",
    label="Sales",
    owner="Vijay",
    summary="An inbound customer enquiry is logged in the sales lead tracker and acknowledged by email.",
    tools=["gmail", "sheets"],
    team="sales",
    people=["u_rohit", "u_neha", "u_imran", "u_divya"],

    workflow_name="Inbound Lead Processing",
    per_person_per_week=9.0,
    steps=[
        Step("gmail", "read", "customer_enquiry", 50, fields=["sender", "subject"]),
        Step("sheets", "create", "lead_row", 70, fields=["customer"]),
        # Optional: some leads also get a follow-up date written on the row.
        Step("sheets", "update", "follow_up_date", 35, probability=0.35, fields=["customer"]),
        Step("gmail", "send", "acknowledgement", 40, fields=["recipient"]),
    ],

    reorder_probability=0.08,
    context_switch_probability=0.40,
    anomaly_probability=0.03,
    is_template=False,
)
