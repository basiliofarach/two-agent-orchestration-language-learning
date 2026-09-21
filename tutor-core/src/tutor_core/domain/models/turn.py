"""Working turn accumulated across the graph (DEC-0010)."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from tutor_core.domain.models.retrieval import RetrievalResult
from tutor_core.domain.models.safety import GeneratedUnit, RedactedText, SafetyFlag


class TurnState(BaseModel):
    """Mutable turn. Field assignment is how the pipeline accumulates it.

    ``extra="forbid"`` still applies. This model is not frozen: immutability
    belongs to the audit record written from a snapshot, not to the in-flight
    object (ARCHITECTURE §5, DEC-0010).
    """

    model_config = ConfigDict(extra="forbid")

    turn_id: UUID
    session_id: UUID
    learner_prompt: RedactedText | None = None
    retrieved: RetrievalResult | None = None
    generated: GeneratedUnit | None = None
    safety_flags: tuple[SafetyFlag, ...] = ()
