"""Working turn accumulated across the graph (DEC-0010)."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from tutor_core.domain.models.learner import LearnerHistorySnapshot, LearnerId
from tutor_core.domain.models.retrieval import RetrievalResult
from tutor_core.domain.models.safety import GeneratedUnit, RedactedText, SafetyFlag
from tutor_core.domain.models.session_baseline import SessionBaseline


class TurnState(BaseModel):
    """Mutable turn. Field assignment is how the pipeline accumulates it.

    ``extra="forbid"`` still applies. This model is not frozen: immutability
    belongs to the audit record written from a snapshot, not to the in-flight
    object (ARCHITECTURE §5, DEC-0010).

    ``requested_history_fields`` and ``requires_unvetted_source`` are set
    when the turn is prepared, before any read. The permission gate judges
    them; retrieval then reads exactly the requested fields (REQ-GATES,
    REQ-HISTORY). ``prompt_safety_flags`` are what the classifier raised
    on the redacted prompt; the record keeps them. ``retrieved`` and
    ``history`` are written by the retrieval node, ``generated`` and
    ``safety_flags`` by the generation node. ``session_baseline`` is the
    session's earlier turns, summarised before the graph runs, for the drift
    gate.
    """

    model_config = ConfigDict(extra="forbid")

    turn_id: UUID
    session_id: UUID
    learner_id: LearnerId
    learner_prompt: RedactedText | None = None
    requested_history_fields: tuple[str, ...] = ()
    requires_unvetted_source: bool = False
    prompt_safety_flags: tuple[SafetyFlag, ...] = ()
    session_baseline: SessionBaseline = SessionBaseline()
    retrieved: RetrievalResult | None = None
    history: LearnerHistorySnapshot | None = None
    generated: GeneratedUnit | None = None
    safety_flags: tuple[SafetyFlag, ...] = ()
