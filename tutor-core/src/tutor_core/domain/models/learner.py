"""Minimal learner identity and the history a read is allowed to return."""

from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tutor_core.domain.models.timestamps import AwareDatetime


class LearnerId(BaseModel):
    """Pseudonymous learner identifier. Not a name and not contact data."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: UUID


HistoryField = Literal["proficiency_level", "events"]


class HistoryFieldSet(BaseModel):
    """Named history fields: a deployment minimum, or what one turn requests.

    The admissible names are the history schema: proficiency and item
    outcomes. Not the pseudonym, not a free column. A name is listed once.
    An empty set is legal and admits nothing (REQ-HISTORY).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    fields: tuple[HistoryField, ...]

    @model_validator(mode="after")
    def names_are_unique(self) -> Self:
        if len(set(self.fields)) != len(self.fields):
            msg = "a history field is listed twice"
            raise ValueError(msg)
        return self

    def admits(self, field: str) -> bool:
        """Whether ``field`` is in this set."""
        return field in self.fields

    def outside(self, requested: tuple[str, ...]) -> tuple[str, ...]:
        """The requested names this set does not admit, in request order."""
        return tuple(field for field in requested if field not in self.fields)


class HistoryItem(BaseModel):
    """One prior item outcome. The allowlist decides whether it is readable."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    item_id: str = Field(min_length=1)
    correct: bool
    occurred_at: AwareDatetime


class LearnerHistorySnapshot(BaseModel):
    """Fields the history port admitted for one learner.

    The field allowlist is a constructor argument of ``LearnerHistoryPort``,
    not a field stored on this snapshot (REQ-HISTORY). ``None`` means that
    field was not read: it was outside the allowlist, the allowlist was
    empty, or retention withheld the history. An admitted field is never
    ``None``. An admitted event list may be empty.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    learner_id: LearnerId
    proficiency_level: str | None = None
    events: tuple[HistoryItem, ...] | None = None

    @field_validator("proficiency_level")
    @classmethod
    def proficiency_is_a_level(cls, value: str | None) -> str | None:
        """An admitted level is non-blank. Absence stays absence."""
        if value is None:
            return None
        if not value.strip():
            msg = "proficiency_level is empty"
            raise ValueError(msg)
        return value
