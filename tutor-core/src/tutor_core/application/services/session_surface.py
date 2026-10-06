"""List sessions, and encode one session's log as server-sent events."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from tutor_core.application.services.service import (
    ApplicationService,
    ExecuteHandler,
    FinaliseHandler,
    PrepareHandler,
)
from tutor_core.domain.models.audit import TurnAuditRecord
from tutor_core.domain.models.session import SessionSummary
from tutor_core.domain.models.stream import TurnStreamEvent
from tutor_core.domain.ports.audit_query import AuditQueryPort
from tutor_core.domain.ports.session_directory import SessionDirectoryPort
from tutor_core.domain.ports.unit_of_work import (
    TransactionalWork,
    TransactionConnection,
    UnitOfWorkPort,
)


class SessionListCommand(BaseModel):
    """The dashboard asked for the sessions it can open."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class PreparedSessions(BaseModel):
    """Nothing to prepare. The read is the execute stage."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class SessionListReceipt(BaseModel):
    """Filled by the list transaction."""

    model_config = ConfigDict(extra="forbid")

    sessions: tuple[SessionSummary, ...] | None = None


class ListSessionsWork(TransactionalWork):
    """Select the session columns the role may read."""

    def __init__(
        self,
        receipt: SessionListReceipt,
        directory: SessionDirectoryPort,
    ) -> None:
        self._receipt = receipt
        self._directory = directory

    async def run(self, connection: TransactionConnection) -> None:
        """Store the list. Do not write."""
        self._receipt.sessions = await self._directory.listed()


class PrepareSessionList(PrepareHandler[SessionListCommand, PreparedSessions]):
    """No fields to check."""

    def run(self, command: SessionListCommand) -> PreparedSessions:
        """Return the empty preparation."""
        return PreparedSessions()


class ExecuteSessionList(ExecuteHandler[PreparedSessions, tuple[SessionSummary, ...]]):
    """Read the directory inside the unit of work."""

    def __init__(self, unit: UnitOfWorkPort, directory: SessionDirectoryPort) -> None:
        self._unit = unit
        self._directory = directory

    async def run(self, prepared: PreparedSessions) -> tuple[SessionSummary, ...]:
        """Return every session."""
        receipt = SessionListReceipt()
        await self._unit.run(ListSessionsWork(receipt, self._directory))
        sessions = receipt.sessions
        if sessions is None:
            msg = "sessions were not read"
            raise ValueError(msg)
        return sessions


class FinaliseSessionList(
    FinaliseHandler[tuple[SessionSummary, ...], tuple[SessionSummary, ...]]
):
    """The list is the result."""

    def run(self, executed: tuple[SessionSummary, ...]) -> tuple[SessionSummary, ...]:
        """Return the list."""
        return executed


class ListSessions(
    ApplicationService[
        SessionListCommand,
        PreparedSessions,
        tuple[SessionSummary, ...],
        tuple[SessionSummary, ...],
    ]
):
    """The container key for the session list. Adds no method (DEC-0011)."""


class StreamCommand(BaseModel):
    """One session's event stream, optionally after an event the client has."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: UUID
    after: str | None = None


class PreparedStream(BaseModel):
    """The session and the resume cursor."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    command: StreamCommand


class StreamReceipt(BaseModel):
    """The frames, filled by the read."""

    model_config = ConfigDict(extra="forbid")

    body: str | None = None


class SseEncoder:
    """``text/event-stream`` frames. ``id`` is what a reconnect sends back."""

    def encode(self, events: tuple[TurnStreamEvent, ...]) -> str:
        """Return every frame, including a quiet halt when the turn stopped."""
        return "".join(self._frame(event) for event in events)

    def _frame(self, event: TurnStreamEvent) -> str:
        data = event.model_dump_json()
        return f"id: {event.event_id}\nevent: {event.kind}\ndata: {data}\n\n"


class StreamWork(TransactionalWork):
    """Read the log and turn it into frames. A halt is the last frame."""

    def __init__(
        self,
        prepared: PreparedStream,
        receipt: StreamReceipt,
        query: AuditQueryPort,
        encoder: SseEncoder,
    ) -> None:
        self._prepared = prepared
        self._receipt = receipt
        self._query = query
        self._encoder = encoder

    async def run(self, connection: TransactionConnection) -> None:
        """Build the frames from records that are already committed."""
        command = self._prepared.command
        records = await self._query.for_session(command.session_id)
        events = self._events(command.session_id, records, command.after)
        self._receipt.body = self._encoder.encode(events)

    def _events(
        self,
        session_id: UUID,
        records: tuple[TurnAuditRecord, ...],
        after: str | None,
    ) -> tuple[TurnStreamEvent, ...]:
        built: list[TurnStreamEvent] = []
        for record in records:
            built.extend(self._record_events(session_id, record))
            if self._halted(record):
                break
        if after is None:
            return tuple(built)
        for index, event in enumerate(built):
            if event.event_id == after:
                return tuple(built[index + 1 :])
        return tuple(built)

    def _record_events(
        self, session_id: UUID, record: TurnAuditRecord
    ) -> tuple[TurnStreamEvent, ...]:
        events: list[TurnStreamEvent] = []
        for gate in record.gate_evaluations:
            events.append(
                TurnStreamEvent(
                    event_id=f"{record.turn_id}:{gate.gate_name}",
                    kind="halt" if gate.decision in {"pause", "stop"} else "gate",
                    turn_id=record.turn_id,
                    session_id=session_id,
                    gate_name=gate.gate_name,
                    decision=gate.decision,
                )
            )
        text = record.output_after_checks
        if text:
            events.append(
                TurnStreamEvent(
                    event_id=f"{record.turn_id}:draft",
                    kind="draft",
                    turn_id=record.turn_id,
                    session_id=session_id,
                    text=text,
                )
            )
        return tuple(events)

    def _halted(self, record: TurnAuditRecord) -> bool:
        halted = {"pause", "stop"}
        return any(gate.decision in halted for gate in record.gate_evaluations)


class PrepareStream(PrepareHandler[StreamCommand, PreparedStream]):
    """Keep the cursor. No read."""

    def run(self, command: StreamCommand) -> PreparedStream:
        """Return the command."""
        return PreparedStream(command=command)


class ExecuteStream(ExecuteHandler[PreparedStream, str]):
    """Read the log and encode it."""

    def __init__(
        self,
        unit: UnitOfWorkPort,
        query: AuditQueryPort,
        encoder: SseEncoder,
    ) -> None:
        self._unit = unit
        self._query = query
        self._encoder = encoder

    async def run(self, prepared: PreparedStream) -> str:
        """Return the ``text/event-stream`` body."""
        receipt = StreamReceipt()
        await self._unit.run(StreamWork(prepared, receipt, self._query, self._encoder))
        body = receipt.body
        if body is None:
            msg = "the event stream was not read"
            raise ValueError(msg)
        return body


class FinaliseStream(FinaliseHandler[str, str]):
    """The encoded body is the result."""

    def run(self, executed: str) -> str:
        """Return the frames."""
        return executed


class StreamSession(ApplicationService[StreamCommand, PreparedStream, str, str]):
    """The container key for the session event stream. Adds no method."""
