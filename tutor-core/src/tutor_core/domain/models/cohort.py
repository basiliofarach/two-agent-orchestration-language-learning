"""Counts a person can review. The report does not decide discrimination."""

from pydantic import BaseModel, ConfigDict, Field


class CohortCount(BaseModel):
    """How many gate rows share one decision. Not a finding about a person."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: str = Field(min_length=1)
    rows: int = Field(ge=0)


class CohortReport(BaseModel):
    """Aggregation over ``turn_audit`` for a human review (REQ-MINOR).

    The architecture supplies the query. It does not supply a verdict, and
    this model has no field that would carry one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    by_decision: tuple[CohortCount, ...]
    refusals: int = Field(ge=0)
    turns: int = Field(ge=0)
