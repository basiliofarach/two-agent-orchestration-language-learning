"""The fields the harness reads. Extra API fields are ignored."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class HealthView(BaseModel):
    """``GET /health``."""

    model_config = ConfigDict(extra="ignore")

    status: str
    database_configured: bool
    mode: Literal["prototype", "simulation"]


class LearnerView(BaseModel):
    """One row of ``GET /learners``."""

    model_config = ConfigDict(extra="ignore")

    learner_id: UUID
    retained: bool


class SessionView(BaseModel):
    """``POST /sessions`` and ``GET /sessions/{id}``."""

    model_config = ConfigDict(extra="ignore")

    session_id: UUID
    learner_id: UUID
    open: bool


class GateRowView(BaseModel):
    """One gate, as ``TurnOutcome.gates`` returns it."""

    model_config = ConfigDict(extra="ignore")

    gate_name: str = Field(min_length=1)
    decision: str = Field(min_length=1)
    policy_rule_id: str | None = None


class TurnOutcomeView(BaseModel):
    """``POST /turns``. ``model_revision`` is how the harness sees a call."""

    model_config = ConfigDict(extra="ignore")

    turn_id: UUID
    session_id: UUID
    status: str
    halted_at: str | None = None
    refused: bool
    sources: tuple[str, ...] = ()
    policy_version: str
    model_revision: str | None = None
    reply: str | None = None
    ai_disclosure: str | None = None
    gates: tuple[GateRowView, ...] = ()


class StoredPromptView(BaseModel):
    """``TurnAuditRecord.learner_prompt``. The text is nested, not a string."""

    model_config = ConfigDict(extra="ignore")

    text: str
    redacted_categories: tuple[str, ...] = ()


class RecordView(BaseModel):
    """The audit record fields the oracle and the tutor role read."""

    model_config = ConfigDict(extra="ignore")

    retrieved_context_ids: tuple[str, ...] = ()
    output_before_checks: str | None = None
    output_after_checks: str | None = None
    learner_prompt: StoredPromptView | None = None


class CitedPassageView(BaseModel):
    """One retrieved passage. The leak scan reads ``content`` and then drops it."""

    model_config = ConfigDict(extra="ignore")

    content: str = Field(min_length=1)


class TurnDetailView(BaseModel):
    """``GET /turns/{id}``."""

    model_config = ConfigDict(extra="ignore")

    record: RecordView = RecordView()
    cited: tuple[CitedPassageView, ...] = ()
    record_intact: bool


class ReplayView(BaseModel):
    """``POST /turns/{id}/replay``. ``outcome`` is the replay comparison."""

    model_config = ConfigDict(extra="ignore")

    turn_id: UUID
    outcome: str = Field(min_length=1)


class AuditView(BaseModel):
    """``GET /sessions/{id}/audit``."""

    model_config = ConfigDict(extra="ignore")

    intact: bool


class HumanActionView(BaseModel):
    """The ``HumanAction`` nested on a successful action response."""

    model_config = ConfigDict(extra="ignore")

    action: str = Field(min_length=1)


class RecordedActionView(BaseModel):
    """``POST /sessions/{id}/turns/{id}/actions``. ``action`` is the row."""

    model_config = ConfigDict(extra="ignore")

    action: HumanActionView
    stopped: bool
