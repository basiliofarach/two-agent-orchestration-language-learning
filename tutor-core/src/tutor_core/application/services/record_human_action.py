"""Record one tutor decision against a turn that is already in the log."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tutor_core.application.services.service import (
    ApplicationService,
    ExecuteHandler,
    FinaliseHandler,
    PrepareHandler,
)
from tutor_core.domain.models.audit import HumanAction, TutorAction
from tutor_core.domain.ports.audit_query import AuditQueryPort
from tutor_core.domain.ports.clock import ClockPort
from tutor_core.domain.ports.human_action import ActionRejected, HumanActionPort
from tutor_core.domain.ports.unit_of_work import (
    TransactionalWork,
    TransactionConnection,
    UnitOfWorkPort,
)


class HumanActionCommand(BaseModel):
    """Approve, edit, override, or stop, as the dashboard submits it (REQ-DASH)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: UUID
    turn_id: UUID
    tutor_id: str = Field(min_length=1)
    action: TutorAction
    edited_output: str | None = None

    @model_validator(mode="after")
    def edit_names_the_text(self) -> "HumanActionCommand":
        """An edit without text cannot be logged, so it is not offered."""
        if self.action != "edit":
            return self
        output = self.edited_output
        if output is None or not output.strip():
            msg = "edited_output is required when the tutor edits"
            raise ValueError(msg)
        return self


class RecordedAction(BaseModel):
    """The row that was appended. ``stopped`` is true only for a stop."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action: HumanAction
    stopped: bool


class ActionReceipt(BaseModel):
    """Filled by the transaction. Empty when the work rolled back."""

    model_config = ConfigDict(extra="forbid")

    recorded: RecordedAction | None = None


class PreparedAction(BaseModel):
    """The command, checked for shape. The turn has not been read yet."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    command: HumanActionCommand


class ActionWork(TransactionalWork):
    """Append the action on the enlisted connection, or roll it back."""

    def __init__(
        self,
        prepared: PreparedAction,
        receipt: ActionReceipt,
        query: AuditQueryPort,
        actions: HumanActionPort,
        clock: ClockPort,
    ) -> None:
        self._prepared = prepared
        self._receipt = receipt
        self._query = query
        self._actions = actions
        self._clock = clock

    async def run(self, connection: TransactionConnection) -> None:
        """Insert the action. A stop marks the session before commit."""
        command = self._prepared.command
        record = await self._query.turn(command.turn_id)
        if record is None or record.session_id != command.session_id:
            msg = "turn is not in this session"
            raise ActionRejected(msg)
        action = HumanAction(
            turn_id=command.turn_id,
            tutor_id=command.tutor_id,
            action=command.action,
            edited_output=command.edited_output,
            acted_at=self._clock.now(),
        )
        await self._actions.append(action, command.session_id)
        self._receipt.recorded = RecordedAction(
            action=action,
            stopped=command.action == "stop",
        )


class PrepareAction(PrepareHandler[HumanActionCommand, PreparedAction]):
    """Accept a command the log can store. No read."""

    def run(self, command: HumanActionCommand) -> PreparedAction:
        """Return the command. Validation already ran on the model."""
        return PreparedAction(command=command)


class ExecuteAction(ExecuteHandler[PreparedAction, RecordedAction]):
    """Write the action in the request's unit of work."""

    def __init__(
        self,
        unit: UnitOfWorkPort,
        query: AuditQueryPort,
        actions: HumanActionPort,
        clock: ClockPort,
    ) -> None:
        self._unit = unit
        self._query = query
        self._actions = actions
        self._clock = clock

    async def run(self, prepared: PreparedAction) -> RecordedAction:
        """Append, or raise ``ActionRejected`` and keep nothing."""
        receipt = ActionReceipt()
        await self._unit.run(
            ActionWork(prepared, receipt, self._query, self._actions, self._clock)
        )
        recorded = receipt.recorded
        if recorded is None:
            msg = "the action was not recorded"
            raise ActionRejected(msg)
        return recorded


class FinaliseAction(FinaliseHandler[RecordedAction, RecordedAction]):
    """The recorded action is the result."""

    def run(self, executed: RecordedAction) -> RecordedAction:
        """Return the action the transaction committed."""
        return executed


class RecordHumanAction(
    ApplicationService[
        HumanActionCommand, PreparedAction, RecordedAction, RecordedAction
    ]
):
    """The container key for a tutor decision. Adds no method (DEC-0011)."""
