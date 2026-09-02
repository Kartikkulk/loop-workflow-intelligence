"""Engineering — a failed CI check becomes a bug ticket.

The middle of the range on purpose. Reading a build log and deciding whether a
failure is new, a known flake, or a real regression is partly judgement, so this
should score below the service desk without being refused outright: the lookup,
the ticket and the notification are mechanical even when the diagnosis is not.

A workflow that lands in the middle is what stops the trust ladder looking like
a formality. Something has to sit between "obviously automate this" and
"obviously do not".
"""

from app.domains.base import DomainPack, Step

DOMAIN = DomainPack(
    key="engineering",
    label="Engineering",
    owner="Kartik",
    summary="Failed pipeline checks are triaged into bug tickets by hand.",
    tools=["github", "jira", "slack"],
    team="engineering",
    people=["u_ishan", "u_naveen", "u_priyanka", "u_tejas"],

    workflow_name="Failed CI check to bug ticket",
    per_person_per_week=8.0,
    steps=[
        Step("github", "read", "failed_check", 50, fields=["repo", "pr_number"]),
        Step("github", "extract", "build_log", 90, fields=["repo", "error_signature"]),
        # Half the time the failure is already known and the search is skipped.
        Step(
            "jira", "search", "existing_bug", 55,
            probability=0.5, fields=["error_signature"],
        ),
        Step("jira", "create", "bug_ticket", 110, fields=["repo", "error_signature", "assignee"]),
        Step("slack", "send", "triage_notice", 35, fields=["channel", "assignee"]),
    ],

    reorder_probability=0.12,
    context_switch_probability=0.45,
    anomaly_probability=0.04,
)
