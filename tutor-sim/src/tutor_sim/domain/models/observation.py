"""What one turn showed the harness. No learner text is stored here."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from tutor_sim.domain.models.case import OutcomeClass
from tutor_sim.domain.models.client_call import CallKind


class ObservedGate(BaseModel):
    """One gate row, as the API returned it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    decision: str = Field(min_length=1)
    policy_rule_id: str | None = None


class ActionAttempt(BaseModel):
    """The dashboard action the tutor role tried, and what the API answered."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: Literal["approve", "edit", "override", "stop", "none"]
    http_status: int
    recorded_action: str | None = None


class LeakHit(BaseModel):
    """An exact string from must_not_contain, found in a field the API exposes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field: str = Field(min_length=1)
    payload_id: str = Field(min_length=1)


class Observation(BaseModel):
    """The fields the oracle compares. Prose is not kept."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str = Field(min_length=1)
    turn_id: UUID
    status: str = Field(min_length=1)
    halted_at: str | None = None
    refused: bool
    sources: tuple[str, ...] = ()
    model_called: bool
    retrieval_ran: bool
    gate_rows: tuple[ObservedGate, ...]
    reply_present: bool
    disclosure_present: bool
    action: ActionAttempt | None = None
    replay_matches: bool
    chain_intact: bool
    leaks: tuple[LeakHit, ...] = ()
    outcome: OutcomeClass


# ``run-YYYYMMDDTHHMMSS``, then ``-2``, ``-3`` for runs in the same second.
# A directory name, never a path: no separator can reach the evidence root.
RunId = Annotated[str, StringConstraints(pattern=r"^run-\d{8}T\d{6}(-[1-9]\d*)?$")]


class Tier1Pointer(BaseModel):
    """The latest Tier 1 run that finished. An aborted run never moves it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: RunId


CaseStep = Literal["submit", "detail", "status", "action", "replay", "audit"]


class CaseFailure(BaseModel):
    """Where an errored case stopped. No response text: a 422 can echo input."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    step: CaseStep
    http_status: int = Field(ge=0)
    # ``None`` when every call succeeded but the turn status was unknown.
    kind: CallKind | None


class CampaignLine(BaseModel):
    """One case the run kept. Exposed text stays out of the evidence file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str = Field(min_length=1)
    errored: bool
    observation: Observation | None = None
    # Absent from lines written before failures were recorded.
    failure: CaseFailure | None = None
