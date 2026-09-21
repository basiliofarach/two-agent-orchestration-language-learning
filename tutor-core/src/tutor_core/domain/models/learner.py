"""Minimal learner identity and the history a read is allowed to return."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from tutor_core.domain.models.timestamps import AwareDatetime


class LearnerId(BaseModel):
    """Pseudonymous learner identifier. Not a name and not contact data."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: UUID


class HistoryItem(BaseModel):
    """One prior item outcome. The allowlist decides whether it is readable."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    item_id: str = Field(min_length=1)
    correct: bool
    occurred_at: AwareDatetime


class LearnerHistorySnapshot(BaseModel):
    """Fields the history port may return: proficiency and item outcomes.

    The field allowlist is a constructor argument of ``LearnerHistoryPort``,
    not a field stored on this snapshot (REQ-HISTORY).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    learner_id: LearnerId
    proficiency_level: str = Field(min_length=1)
    events: tuple[HistoryItem, ...]
