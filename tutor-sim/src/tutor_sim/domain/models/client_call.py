"""A tutor-API call. 404, 409, 422 and 503 are results, not raised."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tutor_sim.domain.models.api_views import (
    AuditView,
    HealthView,
    LearnerView,
    RecordedActionView,
    ReplayView,
    SessionView,
    TurnDetailView,
    TurnOutcomeView,
)

CallKind = Literal[
    "ok",
    "not_found",
    "rejected",
    "session_rejected",
    "errored",
    "unexpected",
]


class ApiCall(BaseModel):
    """The status and, when the call failed, the response text."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    http_status: int = Field(ge=0)
    kind: CallKind
    detail: str = ""


class HealthCall(ApiCall):
    """Health, including the process mode."""

    body: HealthView | None = None


class LearnerCall(ApiCall):
    """The roster the request role can see."""

    body: tuple[LearnerView, ...] = ()


class SessionCall(ApiCall):
    """One session."""

    body: SessionView | None = None


class TurnCall(ApiCall):
    """One submitted turn."""

    body: TurnOutcomeView | None = None


class DetailCall(ApiCall):
    """One recorded turn."""

    body: TurnDetailView | None = None


class ReplayCall(ApiCall):
    """One replay."""

    body: ReplayView | None = None


class AuditCall(ApiCall):
    """One session audit."""

    body: AuditView | None = None


class ActionCall(ApiCall):
    """One tutor action. 409 is ``rejected`` and still a result."""

    body: RecordedActionView | None = None
