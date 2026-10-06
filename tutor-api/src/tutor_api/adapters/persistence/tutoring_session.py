"""Read whether a session is this learner's and still open."""

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

    The application role can read ``id``, ``learner_id``, ``started_at``
    and ``stopped_at`` and nothing else on this table. ``tutor_id`` and
    ``stop_reason`` are not selected. A stopped session is one whose
    ``stopped_at`` is set (ARCHITECTURE §8.3).
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
        row = await self._fetch_one(self._ACTIVE, {"session_id": session_id})
        if row is None:
            msg = "session is not known"
            raise SessionRejected(msg)
        if self._uuid(row[0]) != learner_id.value:
            msg = "session belongs to a different learner"
            raise SessionRejected(msg)
        if self._optional_instant(row[1]) is not None:
            msg = "session is stopped"
            raise SessionRejected(msg)
