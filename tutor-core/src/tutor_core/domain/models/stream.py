"""One server-sent event the dashboard reads for a session (REQ-DASH)."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from tutor_core.domain.models.audit import GateOutcome, TutorAction
from tutor_core.domain.models.verdict import GateStage

StreamKind = Literal["prompt", "gate", "halt", "skipped", "draft", "action"]


class TurnStreamEvent(BaseModel):
    """A prompt, gate verdict, draft or tutor action, already redacted.

    ``event_id`` is stable for the row, so a client that reconnects with
    ``Last-Event-ID`` does not paint the same verdict twice. Events are in
    the order they were recorded, so an action taken on an earlier turn
    after a later turn arrived still comes after the frames a client has
    already seen (REQ-MINOR, REQ-GATES).

    ``kind`` separates a gate that passed (``gate``), fired (``halt``) and
    was never reached (``skipped``) — the three states the log keeps apart.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str = Field(min_length=1)
    kind: StreamKind
    turn_id: UUID
    session_id: UUID
    turn_index: int = Field(ge=0)
    gate_name: GateStage | None = None
    decision: GateOutcome | None = None
    reason: str | None = None
    policy_rule_id: str | None = None
    action: TutorAction | None = None
    text: str | None = None
