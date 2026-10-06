"""Read the rows the pack may export. Selects only."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from tutor_api.evidence.body import SourceDocument
from tutor_api.evidence.survey import ChainSurvey
from tutor_core.domain.models.audit import HumanAction, TurnAuditRecord
from tutor_core.domain.ports.audit_query import AuditQueryPort, AuditRecordUnreadable
from tutor_core.domain.ports.unit_of_work import (
    TransactionalWork,
    TransactionConnection,
)


class ExhibitResult(BaseModel):
    """Documents, turns, and actions gathered for one pack. No write."""

    model_config = ConfigDict(extra="forbid")

    documents: tuple[SourceDocument, ...] = ()
    records: tuple[TurnAuditRecord, ...] = ()
    actions: tuple[HumanAction, ...] = ()
    unreadable_sessions: tuple[UUID, ...] = ()


class ExhibitRead(TransactionalWork):
    """The curation checklist and the log, on the connection it is given.

    Statements are selects. Reviewer names are not selected. A session
    whose record no longer validates is listed and not invented.
    """

    _DOCUMENTS = """
        SELECT source_uri, version, review_status
        FROM kb_document
        ORDER BY source_uri, version, id
        """

    _SESSIONS = "SELECT id FROM tutoring_session ORDER BY started_at, id"

    def __init__(self, query: AuditQueryPort, result: ExhibitResult) -> None:
        self._query = query
        self._result = result

    async def run(self, connection: TransactionConnection) -> None:
        """Fill the result from selects."""
        self._result.documents = self._documents(
            await connection.fetch_all(self._DOCUMENTS, {})
        )
        records: list[TurnAuditRecord] = []
        actions: list[HumanAction] = []
        unreadable: list[UUID] = []
        for row in await connection.fetch_all(self._SESSIONS, {}):
            session_id = self._session_id(row[0])
            try:
                found = await self._query.for_session(session_id)
            except AuditRecordUnreadable:
                unreadable.append(session_id)
                continue
            records.extend(found)
            actions.extend(await self._query.session_actions(session_id))
        self._result.records = tuple(records)
        self._result.actions = tuple(actions)
        self._result.unreadable_sessions = tuple(unreadable)

    def _documents(
        self, rows: tuple[tuple[object, ...], ...]
    ) -> tuple[SourceDocument, ...]:
        return tuple(self._document(row) for row in rows)

    def _document(self, row: tuple[object, ...]) -> SourceDocument:
        if len(row) != 3:
            msg = "kb_document select must return source, version, and status"
            raise ValueError(msg)
        status = self._status(row[2])
        return SourceDocument(
            source_uri=str(row[0]),
            version=str(row[1]),
            review_status=status,
        )

    def _status(self, value: object) -> Literal["pending", "approved", "rejected"]:
        if value == "pending":
            return "pending"
        if value == "approved":
            return "approved"
        if value == "rejected":
            return "rejected"
        msg = "kb_document review_status is not a known status"
        raise ValueError(msg)

    def _session_id(self, value: object) -> UUID:
        return value if isinstance(value, UUID) else UUID(str(value))


class PackRead(TransactionalWork):
    """The chain survey and the exhibits, on one read transaction."""

    def __init__(self, survey: ChainSurvey, exhibits: ExhibitRead) -> None:
        self._survey = survey
        self._exhibits = exhibits

    async def run(self, connection: TransactionConnection) -> None:
        """Read both. Neither writes."""
        await self._survey.run(connection)
        await self._exhibits.run(connection)
