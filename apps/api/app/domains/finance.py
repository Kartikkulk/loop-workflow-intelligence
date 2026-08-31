"""Finance — invoice email to ledger entry.

Owner: Anirudh

The hero workflow. Six people do it, it is highly repetitive, and it carries
two deliberate imperfections the platform needs in order to demonstrate
anything honest:

  * a minority of invoices arrive in a foreign currency, which the generated
    automation gets wrong — so the backtest has real failures to name;
  * the vendor column is renamed part-way through the observation window, so
    self-healing has genuine drift to discover rather than a fixture.
"""

from app.domains.base import DomainPack, Step

DOMAIN = DomainPack(
    key="finance",
    label="Finance",
    owner="Anirudh",
    summary="Accounts payable process supplier invoices into the ledger by hand.",
    tools=["gmail", "pdf", "sheets", "erp"],
    team="accounts_payable",
    people=["u_asha", "u_ravi", "u_meera", "u_dev", "u_priya", "u_karan"],

    workflow_name="Invoice email to ledger entry",
    per_person_per_week=12.0,
    steps=[
        Step("gmail", "read", "invoice_email", 45, fields=["sender", "subject"]),
        Step("pdf", "extract", "fields", 120, fields=["vendor_column", "amount"]),
        # Optional: only a third of instances check the vendor record first.
        # This is what makes "one optional step must still cluster" a real test
        # rather than a hypothetical.
        Step("erp", "search", "vendor_record", 40, probability=0.3, fields=["vendor_column"]),
        Step("sheets", "create", "row", 60, fields=["vendor_column", "amount"]),
        Step("gmail", "send", "confirmation", 40, fields=["recipient"]),
    ],

    reorder_probability=0.06,
    context_switch_probability=0.45,
    anomaly_probability=0.02,
)
