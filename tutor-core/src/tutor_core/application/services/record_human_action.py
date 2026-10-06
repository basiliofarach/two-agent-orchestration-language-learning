"""Record one tutor decision against a turn that is already in the log."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tutor_core.application.services.service import (
    ApplicationService,
    ExecuteHandler,
    FinaliseHandler,
    PrepareHandler,
)
from tutor_core.domain.audit.record_hash import ActionRecordHash
from tutor_core.domain.models.audit import (
    GATE_ORDER,
    HumanAction,
    TurnAuditRecord,
    TutorAction,
)
from tutor_core.domain.ports.audit_query import AuditQueryPort, TurnNotFound
from tutor_core.domain.ports.clock import ClockPort
from tutor_core.domain.ports.human_action import ActionRejected, HumanActionPort
from tutor_core.domain.ports.pii_redaction import PiiRedactionPort
from tutor_core.domain.ports.safety_classifier import SafetyClassifierPort
from tutor_core.domain.ports.session_directory import (
    SessionDirectoryPort,
    SessionNotFound,
)
from tutor_core.domain.ports.unit_of_work import (
    TransactionalWork,
    TransactionConnection,
    UnitOfWorkPort,
)


class HumanActionBody(BaseModel):
    """What the dashboard posts. The path names the session and the turn."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tutor_id: str = Field(min_length=1)
    action: TutorAction
    edited_output: str | None = None

    @model_validator(mode="after")
    def edit_names_the_text(self) -> "HumanActionBody":
        """An edit without text cannot be logged, so it is not offered."""
        if self.action != "edit":
            if self.edited_output is not None:
                msg = "edited_output is sent only when the tutor edits"
                raise ValueError(msg)
            return self
        output = self.edited_output
        if output is None or not output.strip():
            msg = "edited_output is required when the tutor edits"
            raise ValueError(msg)
        return self


class HumanActionCommand(BaseModel):
    """Approve, edit, override, or stop, against one turn (REQ-DASH)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: UUID
    turn_id: UUID
    body: HumanActionBody


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


class ActionRules:
    """What a turn and its session must be for one action to be logged.

    ``approve`` releases the model's draft as it stands, so it needs a
    draft the model wrote, that the agent did not refuse, and that passed
    all four gates. A held draft is released only through ``edit``, which
    puts the tutor's own words on record, or set aside with ``override``
    (Art. 14(4)(d)). Without this, a gate's ``pause`` or ``stop`` was a log
    line the approve button ignored (REQ-GATES: advisory gates do not
    support the claim).

    The database enforces the same rules (``ReleaseRequiresPassedGates``);
    checking here first gives the tutor a precise refusal instead of a
    constraint name, and keeps the rule readable beside the use case. The
    trigger is the backstop a request path cannot skip.
    """

    def check(
        self,
        command: HumanActionCommand,
        record: TurnAuditRecord,
        earlier: tuple[HumanAction, ...],
    ) -> None:
        """Raise ``ActionRejected`` when the action may not follow ``earlier``."""
        action = command.body.action
        if action in {"approve", "edit"} and record.output_before_checks is None:
            msg = "the model did not run on this turn, so there is no draft to release"
            raise ActionRejected(msg)
        if action == "approve" and record.refused:
            msg = "the agent refused this draft; edit or override it instead"
            raise ActionRejected(msg)
        if action == "approve" and not self._passed(record):
            msg = "this draft did not pass every gate; edit or override it instead"
            raise ActionRejected(msg)
        if action != "stop" and any(done.decides() for done in earlier):
            msg = "this turn already has a tutor decision"
            raise ActionRejected(msg)

    def _passed(self, record: TurnAuditRecord) -> bool:
        rows = record.gate_evaluations
        return len(rows) == len(GATE_ORDER) and all(
            row.decision == "pass" for row in rows
        )


class ActionWork(TransactionalWork):
    """Append the action on the enlisted connection, or roll it back."""

    def __init__(  # noqa: PLR0913 — each collaborator is injected (rule 3)
        self,
        prepared: PreparedAction,
        receipt: ActionReceipt,
        query: AuditQueryPort,
        directory: SessionDirectoryPort,
        actions: HumanActionPort,
        clock: ClockPort,
        hasher: ActionRecordHash,
        rules: ActionRules,
    ) -> None:
        self._prepared = prepared
        self._receipt = receipt
        self._query = query
        self._directory = directory
        self._actions = actions
        self._clock = clock
        self._hasher = hasher
        self._rules = rules

    async def run(self, connection: TransactionConnection) -> None:
        """Insert the chained action. A stop marks the session before commit."""
        command = self._prepared.command
        session = await self._directory.get(command.session_id)
        if session is None:
            msg = "session is not known"
            raise SessionNotFound(msg)
        record = await self._query.turn(command.turn_id)
        if record is None or record.session_id != command.session_id:
            msg = "turn is not in this session"
            raise TurnNotFound(msg)
        if not session.open:
            msg = "session is stopped"
            raise ActionRejected(msg)
        self._rules.check(command, record, await self._query.actions(record.turn_id))
        action = await self._sealed(command)
        await self._actions.append(action)
        self._receipt.recorded = RecordedAction(
            action=action, stopped=action.action == "stop"
        )

    async def _sealed(self, command: HumanActionCommand) -> HumanAction:
        head = await self._actions.head(command.session_id)
        body = command.body
        unsealed = HumanAction(
            turn_id=command.turn_id,
            tutor_id=body.tutor_id,
            action=body.action,
            edited_output=body.edited_output,
            acted_at=self._clock.now(),
            session_id=command.session_id,
            action_index=head.action_index,
            previous_action_hash=head.previous_action_hash,
            action_hash="unsealed",
        )
        return unsealed.model_copy(
            update={"action_hash": self._hasher.digest(unsealed)}
        )


class PrepareAction(PrepareHandler[HumanActionCommand, PreparedAction]):
    """Redact and check a tutor's edited reply before anything stores it.

    An edit is text that reaches the learner, written by the tutor rather
    than the model, so it gets the controls the model's draft got at its
    boundaries: PII redaction (REQ-MINOR), and the safety classifier, whose
    high-severity flag refuses the edit as it refuses a draft. The raw
    edit stops here, as the raw prompt stops in ``PrepareTurn``. No read.
    """

    def __init__(
        self, redactor: PiiRedactionPort, classifier: SafetyClassifierPort
    ) -> None:
        self._redactor = redactor
        self._classifier = classifier

    def run(self, command: HumanActionCommand) -> PreparedAction:
        """Return the command, its edited reply redacted, or raise."""
        body = command.body
        if body.edited_output is None:
            return PreparedAction(command=command)
        redacted = self._redactor.redact(body.edited_output).text
        high = tuple(
            flag
            for flag in self._classifier.classify(redacted)
            if flag.severity == "high"
        )
        if high:
            reasons = " ".join(flag.message for flag in high)
            msg = f"the edited reply cannot be released: {reasons}"
            raise ActionRejected(msg)
        edited = body.model_copy(update={"edited_output": redacted})
        return PreparedAction(command=command.model_copy(update={"body": edited}))


class ExecuteAction(ExecuteHandler[PreparedAction, RecordedAction]):
    """Write the action in the request's unit of work."""

    def __init__(  # noqa: PLR0913 — each collaborator is injected (rule 3)
        self,
        unit: UnitOfWorkPort,
        query: AuditQueryPort,
        directory: SessionDirectoryPort,
        actions: HumanActionPort,
        clock: ClockPort,
        hasher: ActionRecordHash,
        rules: ActionRules,
    ) -> None:
        self._unit = unit
        self._query = query
        self._directory = directory
        self._actions = actions
        self._clock = clock
        self._hasher = hasher
        self._rules = rules

    async def run(self, prepared: PreparedAction) -> RecordedAction:
        """Append, or raise and keep nothing."""
        receipt = ActionReceipt()
        await self._unit.run(
            ActionWork(
                prepared,
                receipt,
                self._query,
                self._directory,
                self._actions,
                self._clock,
                self._hasher,
                self._rules,
            )
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
