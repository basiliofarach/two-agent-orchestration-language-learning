"""Sessions, learners, the audit log, tutor actions, and the event stream."""

from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import Response

from tutor_api.routers.deps import (
    Actions,
    Audits,
    Learners,
    Openings,
    SessionReads,
    Sessions,
    Streams,
)
from tutor_api.routers.errors import ProblemMapping
from tutor_core.application.services.read_audit import AuditCommand, AuditView
from tutor_core.application.services.record_human_action import (
    HumanActionBody,
    HumanActionCommand,
    RecordedAction,
)
from tutor_core.application.services.session_surface import (
    LearnerListCommand,
    OpenSessionCommand,
    SessionCommand,
    SessionListCommand,
    StreamCommand,
)
from tutor_core.domain.models.session import LearnerSummary, SessionSummary


class SessionRouter:
    """List, open and read sessions. Each handler is one chain expression."""

    def router(self) -> APIRouter:
        """Return the session routes."""
        problems = ProblemMapping()
        router = APIRouter(tags=["sessions"])
        router.add_api_route(
            "/sessions",
            self.listed,
            methods=["GET"],
            response_model=tuple[SessionSummary, ...],
        )
        router.add_api_route(
            "/sessions",
            self.open,
            methods=["POST"],
            status_code=201,
            response_model=SessionSummary,
            responses=problems.responses(422),
        )
        router.add_api_route(
            "/sessions/{session_id}",
            self.read,
            methods=["GET"],
            response_model=SessionSummary,
            responses=problems.responses(404),
        )
        return router

    async def listed(self, service: Sessions) -> tuple[SessionSummary, ...]:
        """Return the sessions the request role can see, newest first."""
        return (await service.prepare(SessionListCommand()).execute()).finalise()

    async def open(self, body: OpenSessionCommand, service: Openings) -> SessionSummary:
        """Open a session for a retained learner."""
        return (await service.prepare(body).execute()).finalise()

    async def read(self, session_id: UUID, service: SessionReads) -> SessionSummary:
        """Return one session, or 404."""
        command = SessionCommand(session_id=session_id)
        return (await service.prepare(command).execute()).finalise()


class LearnerRouter:
    """The learner ids a session can be opened for. No pseudonym (REQ-MINOR)."""

    def router(self) -> APIRouter:
        """Return the learner route."""
        router = APIRouter(tags=["learners"])
        router.add_api_route(
            "/learners",
            self.listed,
            methods=["GET"],
            response_model=tuple[LearnerSummary, ...],
        )
        return router

    async def listed(self, service: Learners) -> tuple[LearnerSummary, ...]:
        """Return every learner id and whether retention still holds."""
        return (await service.prepare(LearnerListCommand()).execute()).finalise()


class AuditRouter:
    """One session's audit chain, including whether the hashes still link."""

    def router(self) -> APIRouter:
        """Return the audit route."""
        router = APIRouter(tags=["audit"])
        router.add_api_route(
            "/sessions/{session_id}/audit",
            self.read,
            methods=["GET"],
            response_model=AuditView,
            responses=ProblemMapping().responses(404),
        )
        return router

    async def read(self, session_id: UUID, service: Audits) -> AuditView:
        """Return the redacted log and the chain status."""
        prepared = service.prepare(AuditCommand(session_id=session_id))
        return (await prepared.execute()).finalise()


class ActionRouter:
    """Approve, edit, override, or stop. Each one is a chained, logged insert."""

    def router(self) -> APIRouter:
        """Return the action route."""
        router = APIRouter(tags=["actions"])
        router.add_api_route(
            "/sessions/{session_id}/turns/{turn_id}/actions",
            self.record,
            methods=["POST"],
            response_model=RecordedAction,
            responses=ProblemMapping().responses(404, 409),
        )
        return router

    async def record(
        self,
        session_id: UUID,
        turn_id: UUID,
        body: HumanActionBody,
        service: Actions,
    ) -> RecordedAction:
        """Append the action. The path names the session and the turn."""
        command = HumanActionCommand(session_id=session_id, turn_id=turn_id, body=body)
        return (await service.prepare(command).execute()).finalise()


class EventRouter:
    """One session's events, as ``text/event-stream``.

    Each response is the committed log after ``Last-Event-ID``; the
    ``retry`` hint makes ``EventSource`` reconnect for what is new.
    """

    _HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

    def router(self) -> APIRouter:
        """Return the event route."""
        router = APIRouter(tags=["events"])
        router.add_api_route(
            "/sessions/{session_id}/events",
            self.stream,
            methods=["GET"],
            responses=ProblemMapping().responses(404),
        )
        return router

    async def stream(
        self, session_id: UUID, request: Request, service: Streams
    ) -> Response:
        """Return the frames. ``Last-Event-ID`` resumes after that frame."""
        command = StreamCommand(
            session_id=session_id,
            after=request.headers.get("last-event-id"),
        )
        body = (await service.prepare(command).execute()).finalise()
        return Response(
            content=body, media_type="text/event-stream", headers=self._HEADERS
        )
