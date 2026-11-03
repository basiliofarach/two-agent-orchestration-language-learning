"""A campaign report (contract C3). A pending licence is labelled."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tutor_sim.domain.models.case import LabelBasis, OutcomeClass


class CaseResult(BaseModel):
    """One case compared with the expectation fixed before the run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str = Field(min_length=1)
    outcome_ok: bool
    gate_attribution: Literal["right", "wrong", "missed", "n/a"]
    rule_ok: bool | None = None
    errored: bool
    observed: OutcomeClass | None = None


class RateRow(BaseModel):
    """A count over its cases, ``k/n``. No interval is computed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    basis: LabelBasis | None = None
    k: int = Field(ge=0)
    n: int = Field(ge=0)

    @model_validator(mode="after")
    def _k_within_n(self) -> "RateRow":
        if self.k > self.n:
            msg = "k cannot exceed n"
            raise ValueError(msg)
        return self


class InvariantRow(BaseModel):
    """One invariant. A failure fails the run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    invariant_id: str = Field(min_length=1)
    passed: bool


class SimulationReport(BaseModel):
    """Rates, invariants, and whether the licence review is still pending."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    label: str = Field(min_length=1)
    licence_status: Literal["confirmed", "pending"]
    pending_sources: tuple[str, ...] = ()
    rates: tuple[RateRow, ...] = ()
    invariants: tuple[InvariantRow, ...] = ()
    finished: bool
