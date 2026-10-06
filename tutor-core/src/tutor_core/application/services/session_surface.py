"""Sessions and learners for the dashboard, and one session's event stream."""

from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from tutor_core.application.services.service import (
    ApplicationService,
    ExecuteHandler,
    FinaliseHandler,
    PrepareHandler,
)
from tutor_core.domain.models.audit import GateEvaluation, HumanAction, TurnAuditRecord
from tutor_core.domain.models.session import (
    LearnerSummary,
    SessionOpening,
    SessionSummary,
)
from tutor_core.domain.models.stream import StreamKind, TurnStreamEvent
from tutor_core.domain.models.timestamps import AwareDatetime, Timestamped
from tutor_core.domain.ports.audit_query import AuditQueryPort
from tutor_core.domain.ports.clock import ClockPort
from tutor_core.domain.ports.session_directory import (
    SessionDirectoryPort,
    SessionNotFound,
)
from tutor_core.domain.ports.unit_of_work import (
    TransactionalWork,
    TransactionConnection,
    UnitOfWorkPort,
)


class DirectoryRead(BaseModel):
    """Whatever one directory read returned. Filled inside the transaction."""

    model_config = ConfigDict(extra="forbid")

    sessions: tuple[SessionSummary, ...] | None = None
    session: SessionSummary | None = None
    learners: tuple[LearnerSummary, ...] | None = None


# --- list sessions -------------------------------------------------------


class SessionListCommand(BaseModel):
    """The dashboard asked for the sessions it can open."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class PreparedSessions(BaseModel):
    """Nothing to prepare. The read is the execute stage."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ListSessionsWork(TransactionalWork):
    """Select the session columns the role may read."""

    def __init__(self, receipt: DirectoryRead, directory: SessionDirectoryPort) -> None:
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
        receipt = DirectoryRead()
        await self._unit.run(ListSessionsWork(receipt, self._directory))
        if receipt.sessions is None:
            msg = "sessions were not read"
            raise ValueError(msg)
        return receipt.sessions


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


# --- read one session ----------------------------------------------------


class SessionCommand(BaseModel):
    """One session the dashboard opened by id."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: UUID


class ReadSessionWork(TransactionalWork):
    """Select one session, or leave the receipt empty."""

    def __init__(
        self,
        command: SessionCommand,
        receipt: DirectoryRead,
        directory: SessionDirectoryPort,
    ) -> None:
        self._command = command
        self._receipt = receipt
        self._directory = directory

    async def run(self, connection: TransactionConnection) -> None:
        """Store the session. Do not write."""
        self._receipt.session = await self._directory.get(self._command.session_id)


class PrepareSession(PrepareHandler[SessionCommand, SessionCommand]):
    """The id is already a UUID."""

    def run(self, command: SessionCommand) -> SessionCommand:
        """Return the command."""
        return command


class ExecuteSession(ExecuteHandler[SessionCommand, SessionSummary]):
    """Read one session. An unknown id is ``SessionNotFound``."""

    def __init__(self, unit: UnitOfWorkPort, directory: SessionDirectoryPort) -> None:
        self._unit = unit
        self._directory = directory

    async def run(self, prepared: SessionCommand) -> SessionSummary:
        """Return the session."""
        receipt = DirectoryRead()
        await self._unit.run(ReadSessionWork(prepared, receipt, self._directory))
        if receipt.session is None:
            msg = "session is not known"
            raise SessionNotFound(msg)
        return receipt.session


class FinaliseSession(FinaliseHandler[SessionSummary, SessionSummary]):
    """The session is the result."""

    def run(self, executed: SessionSummary) -> SessionSummary:
        """Return the session."""
        return executed


class ReadSession(
    ApplicationService[SessionCommand, SessionCommand, SessionSummary, SessionSummary]
):
    """The container key for one session. Adds no method (DEC-0011)."""


# --- open a session ------------------------------------------------------


class OpenSessionCommand(BaseModel):
    """The tutor opens a session for one learner (REQ-DASH)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    learner_id: UUID
    tutor_id: str = Field(min_length=1)


class PreparedOpening(BaseModel):
    """The command with the id the new session will have."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: UUID
    command: OpenSessionCommand


class OpenSessionWork(TransactionalWork):
    """Open through the directory, then read the row back."""

    def __init__(
        self,
        opening: SessionOpening,
        receipt: DirectoryRead,
        directory: SessionDirectoryPort,
    ) -> None:
        self._opening = opening
        self._receipt = receipt
        self._directory = directory

    async def run(self, connection: TransactionConnection) -> None:
        """Insert through ``open_session``; the read sees this transaction."""
        await self._directory.open(self._opening)
        self._receipt.session = await self._directory.get(self._opening.session_id)


class PrepareOpenSession(PrepareHandler[OpenSessionCommand, PreparedOpening]):
    """Assign the new session's id. No I/O."""

    def run(self, command: OpenSessionCommand) -> PreparedOpening:
        """Return the command with a fresh id."""
        return PreparedOpening(session_id=uuid4(), command=command)


class ExecuteOpenSession(ExecuteHandler[PreparedOpening, SessionSummary]):
    """Open the session at the injected clock (DEC-0010)."""

    def __init__(
        self,
        unit: UnitOfWorkPort,
        directory: SessionDirectoryPort,
        clock: ClockPort,
    ) -> None:
        self._unit = unit
        self._directory = directory
        self._clock = clock

    async def run(self, prepared: PreparedOpening) -> SessionSummary:
        """Return the opened session, or raise and write nothing."""
        opening = SessionOpening(
            session_id=prepared.session_id,
            learner_id=prepared.command.learner_id,
            tutor_id=prepared.command.tutor_id,
            started_at=self._clock.now(),
        )
        receipt = DirectoryRead()
        await self._unit.run(OpenSessionWork(opening, receipt, self._directory))
        if receipt.session is None:
            msg = "the session was not opened"
            raise ValueError(msg)
        return receipt.session


class OpenSession(
    ApplicationService[
        OpenSessionCommand, PreparedOpening, SessionSummary, SessionSummary
    ]
):
    """The container key for opening a session. Adds no method (DEC-0011)."""


# --- list learners -------------------------------------------------------


class LearnerListCommand(BaseModel):
    """The dashboard asked which learners a session can name."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ListLearnersWork(TransactionalWork):
    """Select learner ids and their retention."""

    def __init__(self, receipt: DirectoryRead, directory: SessionDirectoryPort) -> None:
        self._receipt = receipt
        self._directory = directory

    async def run(self, connection: TransactionConnection) -> None:
        """Store the list. Do not write."""
        self._receipt.learners = await self._directory.learners()


class PrepareLearnerList(PrepareHandler[LearnerListCommand, LearnerListCommand]):
    """No fields to check."""

    def run(self, command: LearnerListCommand) -> LearnerListCommand:
        """Return the command."""
        return command


class ExecuteLearnerList(
    ExecuteHandler[LearnerListCommand, tuple[LearnerSummary, ...]]
):
    """Read the learner ids inside the unit of work."""

    def __init__(self, unit: UnitOfWorkPort, directory: SessionDirectoryPort) -> None:
        self._unit = unit
        self._directory = directory

    async def run(self, prepared: LearnerListCommand) -> tuple[LearnerSummary, ...]:
        """Return every learner."""
        receipt = DirectoryRead()
        await self._unit.run(ListLearnersWork(receipt, self._directory))
        if receipt.learners is None:
            msg = "learners were not read"
            raise ValueError(msg)
        return receipt.learners


class FinaliseLearnerList(
    FinaliseHandler[tuple[LearnerSummary, ...], tuple[LearnerSummary, ...]]
):
    """The list is the result."""

    def run(self, executed: tuple[LearnerSummary, ...]) -> tuple[LearnerSummary, ...]:
        """Return the list."""
        return executed


class ListLearners(
    ApplicationService[
        LearnerListCommand,
        LearnerListCommand,
        tuple[LearnerSummary, ...],
        tuple[LearnerSummary, ...],
    ]
):
    """The container key for the learner list. Adds no method (DEC-0011)."""


# --- event stream --------------------------------------------------------


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
    """``text/event-stream`` frames. ``id`` is what a reconnect sends back.

    The body opens with ``retry``: the response is a snapshot of committed
    rows, and the browser's ``EventSource`` reconnects after it with
    ``Last-Event-ID``, receiving only what is new. Holding a request open
    would hold its database connection for as long as a tutor watched.
    """

    RETRY_MILLISECONDS = 2000

    def encode(self, events: tuple[TurnStreamEvent, ...]) -> str:
        """Return the retry hint and every frame."""
        frames = "".join(self._frame(event) for event in events)
        return f"retry: {self.RETRY_MILLISECONDS}\n\n{frames}"

    def _frame(self, event: TurnStreamEvent) -> str:
        data = event.model_dump_json()
        return f"id: {event.event_id}\nevent: {event.kind}\ndata: {data}\n\n"


class TimedEvent(Timestamped):
    """One event and where it sorts: when it was recorded, then its place."""

    at: AwareDatetime
    turn_index: int
    place: int
    event: TurnStreamEvent


class SessionEvents:
    """Turn the committed log into events, in the order they happened.

    Every turn contributes its prompt, its four gate rows and its draft,
    whether or not a gate halted it: a pause holds that turn for the tutor
    and does not end the session. Tutor actions come at the instant they
    were taken, so an approval of turn 0 given after turn 1 arrived is sent
    after turn 1's frames, and a client resuming from turn 1 receives it.
    """

    _GATE_KIND: dict[str, StreamKind] = {
        "pass": "gate",
        "pause": "halt",
        "stop": "halt",
        "not_evaluated": "skipped",
    }

    def events(
        self,
        session_id: UUID,
        records: tuple[TurnAuditRecord, ...],
        actions: tuple[HumanAction, ...],
    ) -> tuple[TurnStreamEvent, ...]:
        """Return every event, oldest first."""
        indexes = {record.turn_id: record.turn_index for record in records}
        timed: list[TimedEvent] = []
        for record in records:
            timed.extend(self._turn(session_id, record))
        for action in actions:
            timed.append(
                self._action(session_id, action, indexes.get(action.turn_id, 0))
            )
        timed.sort(key=lambda item: (item.at, item.turn_index, item.place))
        return tuple(item.event for item in timed)

    def after(
        self, events: tuple[TurnStreamEvent, ...], cursor: str | None
    ) -> tuple[TurnStreamEvent, ...]:
        """The events after ``cursor``. An unknown cursor replays everything.

        That is the ``EventSource`` contract: an id the server cannot place
        is treated as a fresh connection, so the client repaints rather than
        silently missing frames.
        """
        if cursor is None:
            return events
        for index, event in enumerate(events):
            if event.event_id == cursor:
                return events[index + 1 :]
        return events

    def _turn(self, session_id: UUID, record: TurnAuditRecord) -> list[TimedEvent]:
        base: dict[str, object] = {
            "turn_id": record.turn_id,
            "session_id": session_id,
            "turn_index": record.turn_index,
        }
        prompt = TurnStreamEvent.model_validate(
            {
                **base,
                "event_id": f"{record.turn_id}:prompt",
                "kind": "prompt",
                "text": record.learner_prompt.text,
            }
        )
        timed = [self._timed(record, 0, prompt)]
        for place, gate in enumerate(record.gate_evaluations, start=1):
            timed.append(self._timed(record, place, self._gate(gate, base)))
        if record.output_after_checks is not None:
            draft = TurnStreamEvent.model_validate(
                {
                    **base,
                    "event_id": f"{record.turn_id}:draft",
                    "kind": "draft",
                    "text": record.output_after_checks,
                }
            )
            timed.append(self._timed(record, len(record.gate_evaluations) + 1, draft))
        return timed

    def _gate(self, gate: GateEvaluation, base: dict[str, object]) -> TurnStreamEvent:
        return TurnStreamEvent.model_validate(
            {
                **base,
                "event_id": f"{base['turn_id']}:{gate.gate_name}",
                "kind": self._GATE_KIND[gate.decision],
                "gate_name": gate.gate_name,
                "decision": gate.decision,
                "reason": gate.reason,
                "policy_rule_id": gate.policy_rule_id,
            }
        )

    def _action(
        self, session_id: UUID, action: HumanAction, turn_index: int
    ) -> TimedEvent:
        position = (
            str(action.action_index)
            if action.action_index is not None
            else action.acted_at.isoformat()
        )
        event = TurnStreamEvent(
            event_id=f"{action.turn_id}:action:{position}",
            kind="action",
            turn_id=action.turn_id,
            session_id=session_id,
            turn_index=turn_index,
            action=action.action,
            text=action.edited_output,
        )
        return TimedEvent(
            at=action.acted_at, turn_index=turn_index, place=0, event=event
        )

    def _timed(
        self, record: TurnAuditRecord, place: int, event: TurnStreamEvent
    ) -> TimedEvent:
        return TimedEvent(
            at=record.recorded_at,
            turn_index=record.turn_index,
            place=place,
            event=event,
        )


class StreamWork(TransactionalWork):
    """Read the log and turn it into frames."""

    def __init__(  # noqa: PLR0913 — each collaborator is injected (rule 3)
        self,
        prepared: PreparedStream,
        receipt: StreamReceipt,
        query: AuditQueryPort,
        directory: SessionDirectoryPort,
        events: SessionEvents,
        encoder: SseEncoder,
    ) -> None:
        self._prepared = prepared
        self._receipt = receipt
        self._query = query
        self._directory = directory
        self._events = events
        self._encoder = encoder

    async def run(self, connection: TransactionConnection) -> None:
        """Build the frames from records that are already committed."""
        command = self._prepared.command
        if await self._directory.get(command.session_id) is None:
            msg = "session is not known"
            raise SessionNotFound(msg)
        records = await self._query.for_session(command.session_id)
        actions = await self._query.session_actions(command.session_id)
        events = self._events.events(command.session_id, records, actions)
        self._receipt.body = self._encoder.encode(
            self._events.after(events, command.after)
        )


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
        directory: SessionDirectoryPort,
        events: SessionEvents,
        encoder: SseEncoder,
    ) -> None:
        self._unit = unit
        self._query = query
        self._directory = directory
        self._events = events
        self._encoder = encoder

    async def run(self, prepared: PreparedStream) -> str:
        """Return the ``text/event-stream`` body."""
        receipt = StreamReceipt()
        await self._unit.run(
            StreamWork(
                prepared,
                receipt,
                self._query,
                self._directory,
                self._events,
                self._encoder,
            )
        )
        if receipt.body is None:
            msg = "the event stream was not read"
            raise ValueError(msg)
        return receipt.body


class FinaliseStream(FinaliseHandler[str, str]):
    """The encoded body is the result."""

    def run(self, executed: str) -> str:
        """Return the frames."""
        return executed


class StreamSession(ApplicationService[StreamCommand, PreparedStream, str, str]):
    """The container key for the session event stream. Adds no method."""
