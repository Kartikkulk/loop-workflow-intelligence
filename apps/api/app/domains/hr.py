"""HR — leave request approval.

Owner: Vijay          STATUS: template — replace with what you find

A working starting point, not a researched finding. Same instructions as
sales.py: replace tools, people and steps with the real ones, then set
`is_template=False`.

Pick ONE of sales or HR to make real. Two shallow domains are worth less than
one you can explain end to end.
"""

from app.domains.base import DomainPack, Step

DOMAIN = DomainPack(
    key="hr",
    label="People operations",
    owner="Vijay",
    summary="A leave request is checked against policy and recorded in the HR system.",
    tools=["outlook", "hrms", "sheets"],
    team="people_ops",
    people=["u_farah", "u_gopal", "u_sneha"],

    workflow_name="Leave request to HR record",
    per_person_per_week=7.0,
    steps=[
        Step("outlook", "read", "leave_request", 40, fields=["claimant"]),
        Step("hrms", "search", "leave_balance", 60, fields=["claimant"]),
        Step("hrms", "update", "leave_record", 70, fields=["claimant", "status"]),
        Step("outlook", "send", "approval_notice", 35, fields=["claimant"]),
    ],

    reorder_probability=0.10,
    context_switch_probability=0.30,
    anomaly_probability=0.03,
    is_template=True,
)
