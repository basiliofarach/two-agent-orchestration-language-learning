"""A synthetic learner the seed enrols (contract C2)."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Proficiency = Literal["A1", "A2", "B1", "B2"]


class HistoryEventRecord(BaseModel):
    """One seeded history event. The instant is applied later, from the clock."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    item_id: str = Field(min_length=1)
    correct: bool
    days_before_seed: int = Field(ge=0)


class PersonaLearnerRecord(BaseModel):
    """The roster row. The pseudonym is the persona id, and it is synthetic."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    persona_id: str = Field(min_length=1)
    learner_id: UUID
    pseudonym: str = Field(min_length=1)
    proficiency_level: Proficiency
    history: tuple[HistoryEventRecord, ...]

    @model_validator(mode="after")
    def pseudonym_is_the_persona(self) -> "PersonaLearnerRecord":
        """No name is stored. The pseudonym is the persona id."""
        if self.pseudonym != self.persona_id:
            msg = "pseudonym equals the persona id"
            raise ValueError(msg)
        return self
