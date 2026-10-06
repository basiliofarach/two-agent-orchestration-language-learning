"""Sessions, the audit log, tutor actions, and the event stream."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from tutor_api.di.dependency import Provide
from tutor_core.application.services.read_audit import (
    AuditCommand,
    AuditView,
    ReadAudit,
)
from tutor_core.application.services.record_human_action import (
    HumanActionCommand,
    RecordedAction,
    RecordHumanAction,
)
from tutor_core.application.services.session_surface import (
    ListSessions,
    SessionListCommand,
    StreamCommand,
    StreamSession,
)
from tutor_core.domain.models.session import SessionSummary

Sessions = Annotated[ListSessions, Depends(Provide(ListSessions))]
Audits = Annotated[ReadAudit, Depends(Provide(ReadAudit))]
Actions = Annotated[RecordHumanAction, Depends(Provide(RecordHumanAction))]
Streams = Annotated[StreamSession, Depends(Provide(StreamSession))]


class SessionRouter:
    """The dashboard's session list. The handler holds no logic."""

    def router(self) -> APIRouter:
        """Return the session routes."""
        router = APIRouter(tags=["sessions"])
        router.add_api_route(
            "/sessions",
            self.listed,
            methods=["GET"],
            response_model=tuple[SessionSummary, ...],
        )
        return router

    async def listed(self, service: Sessions) -> tuple[SessionSummary, ...]:
        """Return the sessions the request role can see."""
        command = SessionListCommand()
        return (await service.prepare(command).execute()).finalise()


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
        )
        return router

    async def read(self, session_id: UUID, service: Audits) -> AuditView:
        """Return the redacted log and the chain status."""
        prepared = service.prepare(AuditCommand(session_id=session_id))
        return (await prepared.execute()).finalise()


class ActionRouter:
    """Approve, edit, override, or stop. Each one is a logged insert."""

    def router(self) -> APIRouter:
        """Return the action route."""
        router = APIRouter(tags=["actions"])
        router.add_api_route(
            "/sessions/{session_id}/turns/{turn_id}/actions",
            self.record,
            methods=["POST"],
            response_model=RecordedAction,
        )
        return router

    async def record(
        self,
        session_id: UUID,
        turn_id: UUID,
        body: HumanActionCommand,
        service: Actions,
    ) -> RecordedAction:
        """Append the action. The path ids are the ones that are logged."""
        command = body.model_copy(update={"session_id": session_id, "turn_id": turn_id})
        return (await service.prepare(command).execute()).finalise()


class EventRouter:
    """One session's gate and draft events, as ``text/event-stream``."""

    def router(self) -> APIRouter:
        """Return the event route."""
        router = APIRouter(tags=["events"])
        router.add_api_route(
            "/sessions/{session_id}/events", self.stream, methods=["GET"]
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
        return Response(content=body, media_type="text/event-stream")
