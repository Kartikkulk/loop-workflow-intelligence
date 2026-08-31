"""The synthetic-workflow specification behind the seed generator.

Kept separate from the generator script so the tests can import the ground truth
and assert that detection *recovered* it, rather than asserting against whatever
the generator happened to emit.

Design intent: the variance in these specifications is real. Workflow 5 is not
tagged do-not-automate anywhere — it is built to have genuinely high step-order
entropy and genuinely judgement-heavy content, so the F3 detector has to earn
that conclusion from the data.
"""

from __future__ import annotations

from dataclasses import dataclass, field

TEAM_AP = "accounts_payable"
TEAM_AR = "accounts_receivable"
TEAM_FPA = "fp_and_a"

USERS: dict[str, str] = {
    "u_asha": TEAM_AP,
    "u_ravi": TEAM_AP,
    "u_meera": TEAM_AP,
    "u_dev": TEAM_AP,
    "u_priya": TEAM_AP,
    "u_karan": TEAM_AP,
    "u_nikhil": TEAM_AR,
    "u_sana": TEAM_AR,
    "u_arjun": TEAM_AR,
    "u_tara": TEAM_AR,
    "u_vikram": TEAM_FPA,
    "u_leela": TEAM_FPA,
    "u_omar": TEAM_FPA,
    "u_bhavna": TEAM_FPA,
}


@dataclass
class StepSpec:
    """One step in a synthetic workflow."""

    app: str
    action: str
    object_type: str
    # Mean duration in seconds; actual durations are drawn around this.
    seconds: int
    # Probability this step appears at all. Below 1.0 makes an optional step.
    probability: float = 1.0
    # Payload keys this step writes, and how their values are generated.
    payload_keys: list[str] = field(default_factory=list)


@dataclass
class WorkflowSpec:
    """A synthetic workflow, including how much it is allowed to vary."""

    key: str
    name: str
    users: list[str]
    steps: list[StepSpec]
    per_user_per_week: float
    # Probability that two adjacent steps get swapped, per instance.
    reorder_probability: float = 0.0
    # Probability an instance interleaves an A -> B -> A lookup, creating a
    # measurable context switch.
    context_switch_probability: float = 0.0
    # When true the step list is treated as a pool: a random subset in a random
    # order is drawn per instance. This is what produces genuine high entropy.
    freeform: bool = False
    freeform_min: int = 3
    freeform_max: int = 6
    # Probability an instance is a genuine anomaly (an extra unexpected step).
    anomaly_probability: float = 0.0


WORKFLOWS: list[WorkflowSpec] = [
    WorkflowSpec(
        key="invoice_to_ledger",
        name="Invoice email to ledger entry",
        # Six users: above the org threshold of 3, so this must be promoted to
        # an organisational opportunity by F2 step 4.
        users=["u_asha", "u_ravi", "u_meera", "u_dev", "u_priya", "u_karan"],
        per_user_per_week=12.0,
        steps=[
            StepSpec("gmail", "read", "invoice_email", 45, payload_keys=["sender", "subject"]),
            StepSpec("pdf", "extract", "fields", 120, payload_keys=["vendor_column", "amount"]),
            StepSpec("erp", "search", "vendor_record", 40, probability=0.3,
                     payload_keys=["vendor_column"]),
            StepSpec("sheets", "create", "row", 60, payload_keys=["vendor_column", "amount"]),
            StepSpec("gmail", "send", "confirmation", 40, payload_keys=["recipient"]),
        ],
        reorder_probability=0.06,
        context_switch_probability=0.45,
        anomaly_probability=0.02,
    ),
    WorkflowSpec(
        key="weekly_vendor_report",
        name="Weekly vendor ageing report",
        users=["u_vikram", "u_leela", "u_omar", "u_bhavna"],
        per_user_per_week=1.0,
        steps=[
            StepSpec("sheets", "read", "report_source", 90, payload_keys=["sheet_name"]),
            StepSpec("sheets", "search", "overdue_rows", 150, payload_keys=["filter_expr"]),
            StepSpec("sheets", "update", "summary", 240, payload_keys=["sheet_name"]),
            StepSpec("drive", "create", "report_pdf", 60, probability=0.6),
            StepSpec("gmail", "send", "report", 90, payload_keys=["recipient"]),
        ],
        reorder_probability=0.08,
        context_switch_probability=0.25,
        anomaly_probability=0.03,
    ),
    WorkflowSpec(
        key="po_matching",
        name="Purchase order to invoice matching",
        users=["u_asha", "u_ravi", "u_meera", "u_karan", "u_dev"],
        per_user_per_week=8.0,
        steps=[
            StepSpec("erp", "read", "purchase_order", 60, payload_keys=["po_number"]),
            StepSpec("erp", "search", "invoice", 80, payload_keys=["po_number", "amount"]),
            StepSpec("sheets", "update", "match_log", 70, payload_keys=["po_number", "status"]),
            StepSpec("slack", "send", "mismatch_flag", 45, probability=0.25,
                     payload_keys=["status"]),
        ],
        reorder_probability=0.10,
        context_switch_probability=0.35,
        anomaly_probability=0.03,
    ),
    WorkflowSpec(
        key="expense_approval",
        name="Expense claim policy check",
        users=["u_nikhil", "u_sana", "u_arjun", "u_tara"],
        per_user_per_week=6.0,
        steps=[
            StepSpec("gmail", "read", "expense_claim", 50, payload_keys=["claimant", "amount"]),
            StepSpec("drive", "read", "policy_doc", 70, probability=0.35),
            StepSpec("erp", "update", "approval_status", 65, payload_keys=["status", "amount"]),
            StepSpec("gmail", "send", "approval_notice", 40, payload_keys=["claimant"]),
        ],
        reorder_probability=0.12,
        context_switch_probability=0.30,
        anomaly_probability=0.04,
    ),
    WorkflowSpec(
        key="customer_escalation",
        name="Customer escalation handling",
        users=["u_nikhil", "u_sana", "u_arjun"],
        per_user_per_week=4.0,
        # Freeform: every instance draws a different subset in a different
        # order. The step-order entropy this produces is what the variance
        # detector must catch on its own.
        freeform=True,
        freeform_min=3,
        freeform_max=7,
        steps=[
            StepSpec("gmail", "read", "escalation_email", 90, payload_keys=["customer", "tone"]),
            StepSpec("erp", "search", "account_history", 130, payload_keys=["customer"]),
            StepSpec("slack", "send", "internal_consult", 160, payload_keys=["note"]),
            StepSpec("browser", "search", "contract_terms", 140, payload_keys=["note"]),
            StepSpec("drive", "read", "prior_correspondence", 110, payload_keys=["customer"]),
            StepSpec("gmail", "send", "escalation_reply", 300, payload_keys=["customer", "note"]),
            StepSpec("erp", "update", "case_notes", 120, payload_keys=["note"]),
            StepSpec("sheets", "update", "escalation_tracker", 80, payload_keys=["customer"]),
        ],
        reorder_probability=0.0,
        context_switch_probability=0.55,
        anomaly_probability=0.10,
    ),
]

WORKFLOWS_BY_KEY = {w.key: w for w in WORKFLOWS}

# The day, counted from the start of the observation window, on which the
# spreadsheet column is renamed. F8 must discover this from the data.
SCHEMA_CHANGE_DAY = 60
SCHEMA_CHANGE_FROM = "Vendor"
SCHEMA_CHANGE_TO = "Supplier Name"

VENDORS = [
    "Sundaram Steel", "Kaveri Logistics", "Orbit Print Works", "Tessellate Design",
    "Bluepeak Chemicals", "Anand Packaging", "Verdant Facilities", "Northgate IT",
    "Suryodaya Power", "Meridian Freight",
]

CUSTOMERS = [
    "Alcove Retail", "Brightline Foods", "Cadence Motors", "Dunmore Textiles",
    "Everline Pharma", "Fairhaven Group",
]

# Long, judgement-laden note text for the escalation workflow. The free-text
# ratio these produce is what pushes its judgement score up.
ESCALATION_NOTES = [
    "Customer is threatening to escalate to their CFO over the duplicate debit; "
    "they have been with us six years and the relationship matters more than the "
    "3,400 in dispute. Recommend we waive and apologise rather than argue the "
    "contract terms.",
    "Third complaint this quarter from the same account, but the underlying cause "
    "is different each time. Their procurement lead is new and reading the SLA "
    "more literally than the previous incumbent did.",
    "Tone of the email is much sharper than usual for this contact. Worth a phone "
    "call rather than a written reply; putting the contractual position in writing "
    "here will read as defensive.",
    "They are technically outside the return window but the delay was caused by "
    "our own warehouse mis-scan. Approving the credit and noting the cause so it "
    "does not count against their account history.",
    "Ambiguous: the contract says net-30 but the signed addendum says net-45 and "
    "the addendum is the later document. Escalating to legal rather than deciding.",
    "Customer is factually wrong about the delivery date but is a strategic account "
    "in the middle of a renewal. Softening the correction considerably.",
]
