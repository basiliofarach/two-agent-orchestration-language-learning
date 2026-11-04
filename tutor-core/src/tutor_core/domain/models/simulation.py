"""The simulation report the dashboard reads (contract C3)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tutor_core.domain.models.timestamps import AwareDatetime, Timestamped

LabelBasis = Literal["construction", "requirement", "output_dependent"]


class RateRow(BaseModel):
    """A count over its cases, ``k/n``. No interval is computed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    basis: LabelBasis | None = None
    k: int = Field(ge=0)
    n: int = Field(ge=0)

    @model_validator(mode="after")
    def k_within_n(self) -> "RateRow":
        """A count cannot exceed the cases it was taken from."""
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


class SimulationRunSummary(Timestamped):
    """One row of the simulation report list (contract C4, ``summary.json``)."""

    run_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    tier: Literal["1", "2"]
    finished_at: AwareDatetime | None = None
    label: str = Field(min_length=1)
    passed_invariants: bool
    licence_status: Literal["confirmed", "pending"]
    complete: bool
