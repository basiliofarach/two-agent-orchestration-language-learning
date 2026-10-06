"""What the ConductTurn use case receives, passes between stages, and returns."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from tutor_core.domain.models.audit import GateEvaluation, TurnAuditRecord
from tutor_core.domain.models.pipeline import GeneratedDraft
from tutor_core.domain.models.retrieval import RetrievalResult
from tutor_core.domain.models.turn import TurnState
from tutor_core.domain.models.verdict import GateStage

TurnStatus = Literal["awaiting_tutor_approval", "held_for_review"]


class TurnCommand(BaseModel):
    """One learner question, as the tutor dashboard submits it.

    ``prompt`` is raw learner text. It is redacted in the prepare stage and
    the raw string goes no further (REQ-MINOR). ``requested_history_fields``
    names the history the task needs; the permission gate judges it before
    anything is read (REQ-GATES, REQ-HISTORY).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: UUID
    learner_id: UUID
    prompt: str = Field(min_length=1, max_length=2000)
    requested_history_fields: tuple[str, ...] = ()


class PreparedTurn(BaseModel):
    """The redacted, scoped turn the execute stage runs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    turn: TurnState


class ExecutedTurn(BaseModel):
    """The committed audit record, and what the graph produced for display."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    record: TurnAuditRecord
    draft: GeneratedDraft | None
    retrieved: RetrievalResult | None


class TurnOutcome(BaseModel):
    """What the tutor sees after one turn (REQ-GATES, REQ-DASH).

    Nothing reaches the learner from here. A turn whose four gates passed
    awaits the tutor's approval; any other turn is held for review, and
    ``halted_at`` names the gate that held it. ``reply`` carries the
    disclosure beside it whenever there is a reply.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    turn_id: UUID
    session_id: UUID
    turn_index: int = Field(ge=0)
    status: TurnStatus
    halted_at: GateStage | None
    reply: str | None
    ai_disclosure: str | None
    refused: bool
    unsupported_claims: tuple[str, ...]
    sources: tuple[str, ...]
    gates: tuple[GateEvaluation, ...]
    policy_version: str
    model_revision: str | None
    record_hash: str
