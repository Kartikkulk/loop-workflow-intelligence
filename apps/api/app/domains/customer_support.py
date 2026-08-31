"""Customer support — escalation handling.

Owner: Anirudh

This pack exists so the platform can demonstrate restraint.

It is `freeform`: every instance draws a different subset of steps in a
different order, and the work carries long judgement-laden notes. Nothing here
labels it unautomatable — the variance detector has to reach that conclusion
from the data, and there is a test that fails if it stops doing so.

If you are adding a domain and your workflow genuinely looks like this, that is
a finding, not a failure. Surfacing it is the point.
"""

from app.domains.base import DomainPack, Step

DOMAIN = DomainPack(
    key="customer_support",
    label="Customer support",
    owner="Anirudh",
    summary=(
        "Handling an escalated complaint, where the right answer depends on the relationship."
    ),
    tools=["gmail", "erp", "slack", "drive", "browser", "sheets"],
    team="accounts_receivable",
    people=["u_nikhil", "u_sana", "u_arjun"],

    workflow_name="Customer escalation handling",
    per_person_per_week=4.0,
    # A pool, not a sequence: each instance takes 3-7 of these in a random
    # order. That is what produces the step-order entropy the detector catches.
    freeform=True,
    freeform_min=3,
    freeform_max=7,
    steps=[
        Step("gmail", "read", "escalation_email", 90, fields=["customer", "tone"]),
        Step("erp", "search", "account_history", 130, fields=["customer"]),
        Step("slack", "send", "internal_consult", 160, fields=["note"]),
        Step("browser", "search", "contract_terms", 140, fields=["note"]),
        Step("drive", "read", "prior_correspondence", 110, fields=["customer"]),
        Step("gmail", "send", "escalation_reply", 300, fields=["customer", "note"]),
        Step("erp", "update", "case_notes", 120, fields=["note"]),
        Step("sheets", "update", "escalation_tracker", 80, fields=["customer"]),
    ],

    context_switch_probability=0.55,
    anomaly_probability=0.10,
)
