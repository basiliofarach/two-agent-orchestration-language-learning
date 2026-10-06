"""Read a session's audit chain for the dashboard."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from tutor_core.application.services.service import (
    ApplicationService,
    ExecuteHandler,
    FinaliseHandler,
    PrepareHandler,
)
from tutor_core.domain.audit.chain import ChainVerifier
from tutor_core.domain.models.audit import HumanAction, TurnAuditRecord
from tutor_core.domain.ports.audit_query import AuditQueryPort
from tutor_core.domain.ports.unit_of_work import (
    TransactionalWork,
    TransactionConnection,
    UnitOfWorkPort,
)


class AuditCommand(BaseModel):
    """Which session's log the tutor asked to see."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: UUID


class AuditView(BaseModel):
    """The chain, the tutor actions, and whether the hashes still link."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    records: tuple[TurnAuditRecord, ...]
    actions: tuple[HumanAction, ...]
    intact: bool
    break_turn_id: UUID | None


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
        verifier: ChainVerifier,
    ) -> None:
        self._prepared = prepared
        self._receipt = receipt
        self._query = query
        self._verifier = verifier

    async def run(self, connection: TransactionConnection) -> None:
        """Read records and actions. Do not write."""
        session_id = self._prepared.command.session_id
        records = await self._query.for_session(session_id)
        actions: list[HumanAction] = []
        for record in records:
            actions.extend(await self._query.actions(record.turn_id))
        broken = self._verifier.find_break(records)
        self._receipt.view = AuditView(
            records=records,
            actions=tuple(actions),
            intact=broken is None,
            break_turn_id=None if broken is None else broken.turn_id,
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
        verifier: ChainVerifier,
    ) -> None:
        self._unit = unit
        self._query = query
        self._verifier = verifier

    async def run(self, prepared: PreparedAudit) -> AuditView:
        """Return the view, or fail when the read did not fill it."""
        receipt = AuditReceipt()
        await self._unit.run(AuditWork(prepared, receipt, self._query, self._verifier))
        view = receipt.view
        if view is None:
            msg = "the audit log was not read"
            raise ValueError(msg)
        return view


class FinaliseAudit(FinaliseHandler[AuditView, AuditView]):
    """The view is the result."""

    def run(self, executed: AuditView) -> AuditView:
        """Return the committed read."""
        return executed


class ReadAudit(ApplicationService[AuditCommand, PreparedAudit, AuditView, AuditView]):
    """The container key for the audit read. Adds no method (DEC-0011)."""
