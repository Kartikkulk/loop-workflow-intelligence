"""Platform engineering — the overnight build report, typed out by hand.

The simplest workflow in the seed, kept deliberately trivial so that the honest
answer to "what does Kriyā AI do?" can be demonstrated on one screen.

Every morning, whoever is on rota opens the overnight pipeline result, writes
the same page on the wiki, and pastes the link into the team channel. Three
steps, always the same order, nothing to decide. Detection should find it
without help and score it at the top for consistency; if it ever does not,
something upstream is broken.
"""

from app.domains.base import DomainPack, Step

DOMAIN = DomainPack(
    key="devops",
    label="Platform engineering",
    owner="Kartik",
    summary="The overnight build result is written up and posted by hand each morning.",
    tools=["jenkins", "confluence", "slack"],
    team="platform",
    people=["u_dinesh", "u_kavya", "u_omar", "u_ritika", "u_sameer"],

    workflow_name="Overnight build report to the team channel",
    # Once every weekday. Frequency is what turns three trivial steps into
    # real hours.
    per_person_per_week=5.0,
    steps=[
        Step("jenkins", "read", "overnight_build_result", 60, fields=["build_id", "status"]),
        Step("confluence", "create", "build_report_page", 45, fields=["build_id", "status"]),
        Step("slack", "send", "build_summary", 25, fields=["channel", "build_id"]),
    ],

    # No reordering and no optional steps: there is no reason for the order to
    # ever change, and it does not.
    reorder_probability=0.0,
    context_switch_probability=0.10,
    anomaly_probability=0.01,
)
