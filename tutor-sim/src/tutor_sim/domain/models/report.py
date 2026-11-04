"""A campaign report (contract C3). A pending licence is labelled."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tutor_sim.domain.models.case import LabelBasis, OutcomeClass
from tutor_sim.domain.models.timestamps import AwareDatetime


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


class RunSummary(BaseModel):
    """One row of the dashboard's run list (contract C4, ``summary.json``).

    Written beside ``report.json`` and after it, so a listed run always
    has its report. ``label`` is the report's label; the evidence pack
    refuses a pair that disagree.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    tier: Literal["1", "2"]
    finished_at: AwareDatetime | None = None
    label: str = Field(min_length=1)
    passed_invariants: bool
    licence_status: Literal["confirmed", "pending"]
    complete: bool
