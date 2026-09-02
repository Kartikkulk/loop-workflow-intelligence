"""IT service desk — access requests granted by hand.

The hero workflow for an IT audience, and the one most likely to make somebody
in the room wince in recognition. A joiner or a mover needs access to a system,
raises a ticket, and six people on the service desk spend their week doing the
same five clicks: look up the account, add it to a group, close the ticket, tell
them it is done.

It is high volume and almost entirely mechanical, which is exactly the profile
that should score near the top. The one genuinely variable part is left in: some
systems are covered by standing approval and some need a manager to say yes, so
roughly a third of requests take a detour through Slack. That branch is real,
and the automation has to notice it rather than pretend every request is alike.
"""

from app.domains.base import DomainPack, Step

DOMAIN = DomainPack(
    key="it_servicedesk",
    label="IT service desk",
    owner="Kartik",
    summary="Six people grant system access one ticket at a time.",
    tools=["jira", "okta", "slack"],
    team="it_servicedesk",
    people=["u_arun", "u_bhavna", "u_faisal", "u_lata", "u_rahul", "u_shreya"],

    workflow_name="Access request to granted permission",
    per_person_per_week=14.0,
    steps=[
        Step("jira", "read", "access_request", 45, fields=["requester", "system", "ticket_id"]),
        Step("okta", "search", "user_account", 40, fields=["requester"]),
        # Systems under standing approval skip this; the rest need a manager.
        Step(
            "slack", "send", "approval_check", 70,
            probability=0.35, fields=["approver", "requester"],
        ),
        Step("okta", "update", "group_membership", 55, fields=["requester", "system"]),
        # No `status` field here on purpose. Replay withholds decision fields
        # from the automation and then compares against them, so declaring one
        # asks the flow to predict a human judgement from inputs it is not
        # allowed to see — it would score near zero for a reason that says
        # nothing about the workflow. Closing the ticket after a grant is
        # mechanical; the judgement in this workflow is the approval branch
        # below, which is modelled as its own optional step.
        Step("jira", "update", "ticket_status", 40, fields=["ticket_id"]),
        Step("slack", "send", "access_confirmation", 30, fields=["requester", "system"]),
    ],

    reorder_probability=0.05,
    context_switch_probability=0.35,
    anomaly_probability=0.02,
)
