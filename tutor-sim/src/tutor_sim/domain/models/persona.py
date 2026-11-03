"""A virtual pupil. The card never reaches the system under test."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PupilLevel = Literal["A1", "A2", "B1", "B2"]
AgeBand = Literal["12-14", "15-17"]
TraitLevel = Literal["low", "mid", "high"]


class Traits(BaseModel):
    """How the pupil tends to write. Each axis is a fixed label."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    verbosity: TraitLevel
    help_seeking: TraitLevel
    off_task: TraitLevel
    code_switching: TraitLevel


class ErrorRate(BaseModel):
    """One ERRANT error type and its share of the pupil's errors."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    error_type: str = Field(min_length=1)
    rate: float = Field(ge=0, le=1)


class FewShotTurn(BaseModel):
    """One example turn, with the source it was taken from."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: Literal["learner", "tutor"]
    text: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    licence: str = Field(min_length=1)


class PersonaCard(BaseModel):
    """System prompt and few-shot examples for one pupil."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    persona_id: str = Field(min_length=1)
    card_version: str = Field(min_length=1)
    age: int = Field(ge=12, le=17)
    age_band: AgeBand
    cefr_level: PupilLevel
    l1: str = Field(min_length=2, max_length=2)
    traits: Traits
    interests: tuple[str, ...] = Field(min_length=2, max_length=3)
    error_profile: tuple[ErrorRate, ...]
    system_prompt: str = Field(min_length=1)
    few_shot: tuple[FewShotTurn, ...] = Field(min_length=3, max_length=5)
    grounding: tuple[str, ...]

    @model_validator(mode="after")
    def age_matches_band(self) -> "PersonaCard":
        """The band is the age, not a second fact."""
        expected = "12-14" if self.age <= 14 else "15-17"
        if self.age_band != expected:
            msg = "age band does not match the age"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def error_rates_fit(self) -> "PersonaCard":
        """Rates are shares. They cannot sum past one."""
        if sum(item.rate for item in self.error_profile) > 1:
            msg = "error rates sum past one"
            raise ValueError(msg)
        return self
