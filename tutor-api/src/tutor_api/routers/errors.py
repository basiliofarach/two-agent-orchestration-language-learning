"""Map each domain refusal to one HTTP status. No learner text in a body."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from tutor_core.application.services.conduct_turn import TurnFailed
from tutor_core.domain.ports.audit_query import AuditRecordUnreadable, TurnNotFound
from tutor_core.domain.ports.human_action import ActionRejected
from tutor_core.domain.ports.session_directory import (
    SessionNotFound,
    SessionOpenRejected,
)
from tutor_core.domain.ports.tutoring_session import SessionRejected


class Problem(BaseModel):
    """What a refused request returns. The message names the rule, not data."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    detail: str


class ProblemResponse:
    """One exception type answered with one status.

    The message is the domain exception's own, which names the refusal
    ("session is stopped") and never the learner text or the SQL behind it
    (REQ-MINOR).
    """

    def __init__(self, status_code: int) -> None:
        self._status_code = status_code

    async def __call__(self, request: Request, exc: Exception) -> JSONResponse:
        """Return the refusal."""
        return JSONResponse(
            status_code=self._status_code,
            content=Problem(detail=str(exc)).model_dump(),
        )


class ProblemMapping:
    """Register every refusal on an application.

    - 404: the session or turn does not exist.
    - 409: the state refuses the change — a stopped session, a turn already
      decided, a stale chain link, or a record that no longer validates.
    - 422: a turn or session the request named cannot be used for it.
    - 503: the turn failed and rolled back; nothing was recorded.
    """

    _STATUSES: tuple[tuple[type[Exception], int], ...] = (
        (SessionNotFound, 404),
        (TurnNotFound, 404),
        (ActionRejected, 409),
        (AuditRecordUnreadable, 409),
        (SessionRejected, 422),
        (SessionOpenRejected, 422),
        (TurnFailed, 503),
    )

    def install(self, app: FastAPI) -> None:
        """Add one handler per refusal."""
        for exception, status_code in self._STATUSES:
            app.add_exception_handler(exception, ProblemResponse(status_code))

    def responses(self, *statuses: int) -> dict[int | str, dict[str, object]]:
        """OpenAPI entries for the statuses a route can answer with."""
        return {status: {"model": Problem} for status in statuses}
