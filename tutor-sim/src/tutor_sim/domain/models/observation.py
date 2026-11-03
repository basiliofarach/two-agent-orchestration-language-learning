"""What one turn showed the harness. No learner text is stored here."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from tutor_sim.domain.models.case import OutcomeClass


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


class CampaignLine(BaseModel):
    """One case the run kept. Exposed text stays out of the evidence file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str = Field(min_length=1)
    errored: bool
    observation: Observation | None = None
