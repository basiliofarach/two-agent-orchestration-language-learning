"""List sessions from the columns the request role may select."""

from datetime import datetime
from uuid import UUID

from tutor_api.adapters.persistence.base import BaseRepository
from tutor_core.domain.models.session import SessionSummary
from tutor_core.domain.ports.session_directory import SessionDirectoryPort
from tutor_core.domain.ports.unit_of_work import TransactionConnection


class PostgresSessionDirectory(BaseRepository, SessionDirectoryPort):
    """Select ``id``, ``learner_id`` and ``stopped_at``. Nothing else.

    ``started_at`` is not granted, so the order is the session id. The
    adapter cannot update ``stopped_at``; a stop goes through the security
    definer the human-action adapter calls (REQ-DASH).
    """

    _LIST = """
        SELECT id, learner_id, stopped_at
        FROM tutoring_session
        ORDER BY id
        """

    _ONE = """
        SELECT id, learner_id, stopped_at
        FROM tutoring_session
        WHERE id = :session_id
        """

    def __init__(self, connection: TransactionConnection) -> None:
        super().__init__(connection)

    async def listed(self) -> tuple[SessionSummary, ...]:
        """Return every session the role can see."""
        rows = await self._fetch_all(self._LIST, {})
        return tuple(self._summary(row) for row in rows)

    async def get(self, session_id: UUID) -> SessionSummary | None:
        """Return one session, or ``None`` when the id is unknown."""
        row = await self._fetch_one(self._ONE, {"session_id": session_id})
        if row is None:
            return None
        return self._summary(row)

    def _summary(self, row: tuple[object, ...]) -> SessionSummary:
        return SessionSummary(
            session_id=self._uuid(row[0]),
            learner_id=self._uuid(row[1]),
            open=not self._stopped(row[2]),
        )

    def _uuid(self, value: object) -> UUID:
        if isinstance(value, UUID):
            return value
        return UUID(str(value))

    def _stopped(self, value: object) -> bool:
        if value is None:
            return False
        if isinstance(value, datetime):
            if value.utcoffset() is None:
                msg = "session stop time must be timezone-aware"
                raise ValueError(msg)
            return True
        msg = "session stop time is not a timestamp"
        raise ValueError(msg)
