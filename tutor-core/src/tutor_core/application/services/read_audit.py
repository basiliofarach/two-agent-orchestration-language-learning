"""Read a session's audit chain, or one turn with what it cited."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from tutor_core.application.services.service import (
    ApplicationService,
    ExecuteHandler,
    FinaliseHandler,
    PrepareHandler,
)
from tutor_core.domain.audit.chain import ChainVerifier
from tutor_core.domain.audit.record_hash import AuditRecordHash
from tutor_core.domain.models.audit import HumanAction, TurnAuditRecord
from tutor_core.domain.models.retrieval import Snippet
from tutor_core.domain.models.session import SessionSummary
from tutor_core.domain.ports.audit_query import (
    AuditQueryPort,
    AuditRecordUnreadable,
    TurnNotFound,
)
from tutor_core.domain.ports.session_directory import (
    SessionDirectoryPort,
    SessionNotFound,
)
from tutor_core.domain.ports.unit_of_work import (
    TransactionalWork,
    TransactionConnection,
    UnitOfWorkPort,
)

# --- one session's chain -------------------------------------------------


class AuditCommand(BaseModel):
    """Which session's log the tutor asked to see."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: UUID


class AuditView(BaseModel):
    """The chain, the tutor actions, and whether both still link.

    ``intact`` covers the turn chain and the action chain. A turn whose rows
    no longer validate is a break with reason ``unreadable``: the records
    cannot be shown, and the view says which turn stopped them, rather than
    the route failing (REQ-AUDIT). ``unchained_actions`` counts actions
    written before the action chain existed; they are listed, not verified.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    records: tuple[TurnAuditRecord, ...]
    actions: tuple[HumanAction, ...]
    intact: bool
    break_turn_id: UUID | None
    break_reason: Literal["tampered", "excised", "unreadable"] | None = None
    action_break_index: int | None = None
    unchained_actions: int = Field(default=0, ge=0)


class AuditReceipt(BaseModel):
    """Filled inside the read transaction."""

    model_config = ConfigDict(extra="forbid")

    view: AuditView | None = None


class PreparedAudit(BaseModel):
    """The session to read."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    command: AuditCommand


class AuditWork(TransactionalWork):
    """Select the log on the enlisted connection."""

    def __init__(
        self,
        prepared: PreparedAudit,
        receipt: AuditReceipt,
        query: AuditQueryPort,
        directory: SessionDirectoryPort,
        verifier: ChainVerifier,
    ) -> None:
        self._prepared = prepared
        self._receipt = receipt
        self._query = query
        self._directory = directory
        self._verifier = verifier

    async def run(self, connection: TransactionConnection) -> None:
        """Read records and actions, and verify both chains. Do not write."""
        session_id = self._prepared.command.session_id
        if await self._directory.get(session_id) is None:
            msg = "session is not known"
            raise SessionNotFound(msg)
        actions = await self._query.session_actions(session_id)
        try:
            records = await self._query.for_session(session_id)
        except AuditRecordUnreadable as unreadable:
            self._receipt.view = AuditView(
                records=(),
                actions=actions,
                intact=False,
                break_turn_id=unreadable.turn_id,
                break_reason="unreadable",
            )
            return
        self._receipt.view = self._view(records, actions)

    def _view(
        self,
        records: tuple[TurnAuditRecord, ...],
        actions: tuple[HumanAction, ...],
    ) -> AuditView:
        broken = self._verifier.find_break(records)
        action_break = self._verifier.find_action_break(actions)
        if broken is None and action_break is not None:
            break_turn: UUID | None = action_break.turn_id
            reason = action_break.reason
        elif broken is not None:
            break_turn, reason = broken.turn_id, broken.reason
        else:
            break_turn, reason = None, None
        return AuditView(
            records=records,
            actions=actions,
            intact=broken is None and action_break is None,
            break_turn_id=break_turn,
            break_reason=reason,
            action_break_index=(
                None if action_break is None else action_break.action_index
            ),
            unchained_actions=sum(1 for action in actions if not action.chained()),
        )


class PrepareAudit(PrepareHandler[AuditCommand, PreparedAudit]):
    """Keep the session id. No read."""

    def run(self, command: AuditCommand) -> PreparedAudit:
        """Return the command."""
        return PreparedAudit(command=command)


class ExecuteAudit(ExecuteHandler[PreparedAudit, AuditView]):
    """Read inside the unit of work so the connection closes."""

    def __init__(
        self,
        unit: UnitOfWorkPort,
        query: AuditQueryPort,
        directory: SessionDirectoryPort,
        verifier: ChainVerifier,
    ) -> None:
        self._unit = unit
        self._query = query
        self._directory = directory
        self._verifier = verifier

    async def run(self, prepared: PreparedAudit) -> AuditView:
        """Return the view, or fail when the read did not fill it."""
        receipt = AuditReceipt()
        await self._unit.run(
            AuditWork(prepared, receipt, self._query, self._directory, self._verifier)
        )
        if receipt.view is None:
            msg = "the audit log was not read"
            raise ValueError(msg)
        return receipt.view


class FinaliseAudit(FinaliseHandler[AuditView, AuditView]):
    """The view is the result."""

    def run(self, executed: AuditView) -> AuditView:
        """Return the committed read."""
        return executed


class ReadAudit(ApplicationService[AuditCommand, PreparedAudit, AuditView, AuditView]):
    """The container key for the audit read. Adds no method (DEC-0011)."""


# --- one turn ------------------------------------------------------------


class TurnAuditCommand(BaseModel):
    """Which turn the audit page opened."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    turn_id: UUID


class TurnDetail(BaseModel):
    """One turn as the audit page shows it (REQ-DASH, REQ-AUDIT).

    ``cited`` is the vetted chunk text the draft was grounded in — curated
    material, not learner text — so the tutor sees the retrieved context,
    not only its ids. ``record_intact`` is this record's own digest check;
    whether the session chain links is the session audit's question.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    session: SessionSummary
    record: TurnAuditRecord
    actions: tuple[HumanAction, ...]
    cited: tuple[Snippet, ...]
    record_intact: bool


class TurnReceipt(BaseModel):
    """Filled inside the read transaction."""

    model_config = ConfigDict(extra="forbid")

    detail: TurnDetail | None = None


class TurnWork(TransactionalWork):
    """Select one record, its actions, its citations and its session."""

    def __init__(  # noqa: PLR0913 — each collaborator is injected (rule 3)
        self,
        command: TurnAuditCommand,
        receipt: TurnReceipt,
        query: AuditQueryPort,
        directory: SessionDirectoryPort,
        hasher: AuditRecordHash,
    ) -> None:
        self._command = command
        self._receipt = receipt
        self._query = query
        self._directory = directory
        self._hasher = hasher

    async def run(self, connection: TransactionConnection) -> None:
        """Read the turn. An unknown turn is ``TurnNotFound``."""
        record = await self._query.turn(self._command.turn_id)
        if record is None:
            msg = "turn is not known"
            raise TurnNotFound(msg)
        session = await self._directory.get(record.session_id)
        if session is None:
            msg = "the turn's session is not known"
            raise SessionNotFound(msg)
        self._receipt.detail = TurnDetail(
            session=session,
            record=record,
            actions=await self._query.actions(record.turn_id),
            cited=await self._query.citations(record.turn_id),
            record_intact=record.record_hash == self._hasher.digest(record),
        )


class PrepareTurnRead(PrepareHandler[TurnAuditCommand, TurnAuditCommand]):
    """The id is already a UUID."""

    def run(self, command: TurnAuditCommand) -> TurnAuditCommand:
        """Return the command."""
        return command


class ExecuteTurnRead(ExecuteHandler[TurnAuditCommand, TurnDetail]):
    """Read inside the unit of work so the connection closes."""

    def __init__(
        self,
        unit: UnitOfWorkPort,
        query: AuditQueryPort,
        directory: SessionDirectoryPort,
        hasher: AuditRecordHash,
    ) -> None:
        self._unit = unit
        self._query = query
        self._directory = directory
        self._hasher = hasher

    async def run(self, prepared: TurnAuditCommand) -> TurnDetail:
        """Return the turn detail."""
        receipt = TurnReceipt()
        await self._unit.run(
            TurnWork(prepared, receipt, self._query, self._directory, self._hasher)
        )
        if receipt.detail is None:
            msg = "the turn was not read"
            raise ValueError(msg)
        return receipt.detail


class FinaliseTurnRead(FinaliseHandler[TurnDetail, TurnDetail]):
    """The detail is the result."""

    def run(self, executed: TurnDetail) -> TurnDetail:
        """Return the detail."""
        return executed


class ReadTurn(
    ApplicationService[TurnAuditCommand, TurnAuditCommand, TurnDetail, TurnDetail]
):
    """The container key for one turn's audit page. Adds no method."""
