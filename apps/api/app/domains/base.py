"""The shape of a domain pack.

A domain pack is one file describing one team's repetitive work. Adding a
domain means adding a file here — no change to detection, scoring, the engine,
or anything else. That is the whole point: five people can add domains in
parallel without touching each other's code or the core.

See domains/README.md for the copy-paste guide.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Step:
    """One observable action in a workflow.

    `app` and `action` should come from the canonical vocabulary so detection
    can compare across domains — but an unknown app is fine too, it registers
    itself the first time it is seen.
    """

    app: str
    action: str
    object_type: str
    #: Typical duration in seconds. Actual durations vary around this.
    seconds: int
    #: Probability this step happens at all. Below 1.0 makes it optional.
    probability: float = 1.0
    #: Payload keys this step writes. Used to make the flow definition concrete.
    fields: list[str] = field(default_factory=list)


@dataclass
class DomainPack:
    """One team, one repetitive workflow.

    Deliberately one workflow per domain. A domain with five workflows is
    harder to explain and no more convincing than a domain with one that is
    clearly understood end to end.
    """

    #: Stable identifier, lowercase. Used as the workflow key in the event log.
    key: str
    #: Human label shown in the console.
    label: str
    #: Who on the team owns this pack.
    owner: str
    #: One-line description of what this team does.
    summary: str

    #: The applications this team's work touches. Shown on the Observation
    #: screen so it is obvious what a collector needs to see for this domain.
    tools: list[str]

    #: Team identifier the people belong to.
    team: str
    #: The people observed doing this work. More than three makes the detected
    #: workflow an organisational opportunity rather than a personal habit.
    people: list[str]

    #: The workflow itself.
    workflow_name: str
    steps: list[Step]
    #: How often one person does this, per week.
    per_person_per_week: float

    # ── how much the work varies ────────────────────────────────────────
    #: Probability two adjacent steps swap, per instance.
    reorder_probability: float = 0.0
    #: Probability an instance interleaves an unrelated lookup, which creates a
    #: measurable context switch and therefore Interruption Tax.
    context_switch_probability: float = 0.35
    #: Probability of a genuine one-off anomaly.
    anomaly_probability: float = 0.02
    #: When true, each instance draws a random subset of `steps` in a random
    #: order. This is how a genuinely judgement-heavy workflow behaves, and it
    #: is what the variance detector has to notice on its own.
    freeform: bool = False
    freeform_min: int = 3
    freeform_max: int = 6

    #: Set to True for a pack that is a starting point rather than researched
    #: reality. The console labels these, so nobody mistakes a template for a
    #: finding.
    is_template: bool = False

    def __post_init__(self) -> None:
        if not self.steps:
            raise ValueError(f"domain '{self.key}' has no steps")
        if not self.people:
            raise ValueError(f"domain '{self.key}' has no people")
