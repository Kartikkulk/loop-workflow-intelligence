"""Seed constants shared by the generator and the tests.

The workflows themselves now live in `app/domains/` — one file per team, one
workflow each — so adding a domain never touches this file. What remains here
is the handful of facts the generator needs that are not domain-specific.
"""

from __future__ import annotations

from app.domains import DOMAINS, DOMAINS_BY_KEY, PEOPLE

# Re-exported so callers do not need to know where domains are assembled.
USERS = PEOPLE

#: Day, counted from the start of the observation window, on which the finance
#: spreadsheet column is renamed. F8 self-healing must discover this from the
#: data rather than from configuration.
SCHEMA_CHANGE_DAY = 60
SCHEMA_CHANGE_FROM = "Vendor"
SCHEMA_CHANGE_TO = "Supplier Name"

VENDORS = [
    "Sundaram Steel", "Kaveri Logistics", "Orbit Print Works", "Tessellate Design",
    "Bluepeak Chemicals", "Anand Packaging", "Verdant Facilities", "Northgate IT",
    "Suryodaya Power", "Meridian Freight",
]

#: The systems an IT service desk grants access to. Ordinary enterprise tools,
#: because the point of the workflow is that the request is routine.
IT_SYSTEMS = [
    "Salesforce", "Confluence", "AWS Production", "Jenkins", "Tableau",
    "GitHub Enterprise", "SAP", "Zendesk", "Datadog", "VPN",
]

#: Systems that are never granted at the level asked for. A request for these
#: comes back reduced, and the service desk records what was actually granted
#: rather than what was requested — which is the gap a generated flow has no
#: rule for, and therefore the failure an honest backtest has to name.
PRIVILEGED_SYSTEMS = {"AWS Production", "SAP", "VPN"}

#: Repositories the engineering team triages failures in.
REPOSITORIES = [
    "checkout-service", "billing-api", "web-console", "auth-gateway",
    "notification-worker", "reporting-etl",
]

#: Build failure signatures. Short and mechanical: the diagnosis is the
#: judgement, the signature itself is just a string that repeats.
ERROR_SIGNATURES = [
    "TimeoutError in integration suite",
    "npm ERR! peer dependency conflict",
    "OOMKilled during asset build",
    "flaky: test_checkout_retry",
    "connection refused: postgres:5432",
    "TypeError: cannot read property of undefined",
]

CUSTOMERS = [
    "Alcove Retail", "Brightline Foods", "Cadence Motors", "Dunmore Textiles",
    "Everline Pharma", "Fairhaven Group",
]

#: Long, judgement-laden note text. The free-text ratio these produce is the
#: measured signal behind the judgement score that flags a workflow
#: DO NOT AUTOMATE, so they have to read like real human deliberation.
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

__all__ = [
    "CUSTOMERS",
    "ERROR_SIGNATURES",
    "IT_SYSTEMS",
    "PRIVILEGED_SYSTEMS",
    "REPOSITORIES",
    "DOMAINS",
    "DOMAINS_BY_KEY",
    "ESCALATION_NOTES",
    "PEOPLE",
    "SCHEMA_CHANGE_DAY",
    "SCHEMA_CHANGE_FROM",
    "SCHEMA_CHANGE_TO",
    "USERS",
    "VENDORS",
]
