"""Gate verdicts. A verdict is a decision, not a new fact about the turn."""

from typing import Literal

from pydantic import Field

from tutor_core.domain.models.timestamps import AwareDatetime, Timestamped

GateDecision = Literal["pass", "pause", "stop"]

GateStage = Literal[
    "context_and_permission",
    "conflict_and_ambiguity",
    "sensitivity_and_high_stakes",
    "drift_and_anomaly",
]


class GateVerdict(Timestamped):
    """Decision returned by one gate (DEC-0005, REQ-GATES, REQ-POLICY).

    ``decision`` is ``pass``, ``pause``, or ``stop``. The model carries
    ``gate_name``, ``reason``, and ``policy_rule_id``. It carries no safety
    flags: flags are produced by the output checks and live on the turn.
    ``evaluated_at`` is the clock read when the gate was consulted, before
    the stage it guards ran; ``Timestamped`` keeps it UTC (DEC-0010).
    """

    gate_name: str = Field(min_length=1)
    decision: GateDecision
    reason: str = Field(min_length=1)
    policy_rule_id: str = Field(min_length=1)
    evaluated_at: AwareDatetime | None = None
