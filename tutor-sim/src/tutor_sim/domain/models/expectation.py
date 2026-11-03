"""The expectation table. A label comes from here, not from a judge."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tutor_sim.domain.models.case import Expected, Intent


class ExpectationRow(BaseModel):
    """One intent and variant, and the expectation that applies to it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    intent: Intent
    variant: Literal["canonical", "noisy"]
    expected: Expected


class ExpectationTable(BaseModel):
    """Every label for one policy version."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_version: str = Field(min_length=1)
    rows: tuple[ExpectationRow, ...]
