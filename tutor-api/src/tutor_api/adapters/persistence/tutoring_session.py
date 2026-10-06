"""Read whether a session is this learner's and still open."""

from datetime import datetime
from uuid import UUID

from tutor_api.adapters.persistence.base import BaseRepository
from tutor_core.domain.models.learner import LearnerId
from tutor_core.domain.ports.tutoring_session import (
    SessionRejected,
    TutoringSessionPort,
)
from tutor_core.domain.ports.unit_of_work import TransactionConnection


class PostgresTutoringSession(BaseRepository, TutoringSessionPort):
    """One select, on the request connection. No insert, update, or delete.

    The application role can read ``id``, ``learner_id`` and ``stopped_at``
    and nothing else on this table. ``tutor_id`` and ``stop_reason`` are
    not selected. A stopped session is one whose ``stopped_at`` is set
    (ARCHITECTURE §8.3).
    """

    _ACTIVE = """
        SELECT learner_id, stopped_at
        FROM tutoring_session
        WHERE id = :session_id
        """

    def __init__(self, connection: TransactionConnection) -> None:
        super().__init__(connection)

    async def require_active(self, session_id: UUID, learner_id: LearnerId) -> None:
        """Refuse before the caller retrieves or appends."""
        row = await self._fetch_one(
            self._ACTIVE,
            {"session_id": session_id},
        )
        if row is None:
            msg = "session is not known"
            raise SessionRejected(msg)
        owner = self._learner(row[0])
        if owner != learner_id.value:
            msg = "session belongs to a different learner"
            raise SessionRejected(msg)
        if self._stopped(row[1]):
            msg = "session is stopped"
            raise SessionRejected(msg)

    def _learner(self, value: object) -> UUID:
        if isinstance(value, UUID):
            return value
        if isinstance(value, str):
            return UUID(value)
        msg = "session learner is not an identifier"
        raise ValueError(msg)

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
