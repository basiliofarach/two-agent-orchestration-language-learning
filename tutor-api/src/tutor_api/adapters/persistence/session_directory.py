"""List, read and open sessions from the columns the request role may select."""

from uuid import UUID

from tutor_api.adapters.persistence.base import BaseRepository
from tutor_api.adapters.persistence.schema import OpenSessionFunction
from tutor_api.adapters.persistence.sealed import SealedValue
from tutor_core.domain.models.session import (
    LearnerSummary,
    SessionOpening,
    SessionSummary,
)
from tutor_core.domain.ports.clock import ClockPort
from tutor_core.domain.ports.session_directory import (
    SessionDirectoryPort,
    SessionOpenRejected,
)
from tutor_core.domain.ports.unit_of_work import TransactionConnection


class PostgresSessionDirectory(BaseRepository, SessionDirectoryPort):
    """Select ``id``, ``learner_id``, ``started_at`` and ``stopped_at``.

    Nothing else on ``tutoring_session`` is granted. Opening goes through
    ``open_session``, a security definer, so the role holds no INSERT; the
    function refuses an unknown or purged learner with ``OS001``. The
    adapter cannot update ``stopped_at``: a stop goes through the
    human-action adapter (REQ-DASH).
    """

    _COLUMNS = "id, learner_id, started_at, stopped_at"

    _LIST = f"""
        SELECT {_COLUMNS}
        FROM tutoring_session
        ORDER BY started_at DESC, id
        """

    _ONE = f"""
        SELECT {_COLUMNS}
        FROM tutoring_session
        WHERE id = :session_id
        """

    _OPEN = """
        SELECT open_session(
            CAST(:session_id AS uuid),
            CAST(:learner_id AS uuid),
            :tutor_id,
            :started_at
        )
        """

    _LEARNERS = """
        SELECT learner_id, retain_until
        FROM learner
        ORDER BY learner_id
        """

    def __init__(
        self,
        connection: TransactionConnection,
        sealed: SealedValue,
        clock: ClockPort,
    ) -> None:
        super().__init__(connection)
        self._sealed = sealed
        self._clock = clock

    async def listed(self) -> tuple[SessionSummary, ...]:
        """Return every session the role can see, newest first."""
        rows = await self._fetch_all(self._LIST)
        return tuple(self._summary(row) for row in rows)

    async def get(self, session_id: UUID) -> SessionSummary | None:
        """Return one session, or ``None`` when the id is unknown."""
        row = await self._fetch_one(self._ONE, {"session_id": session_id})
        if row is None:
            return None
        return self._summary(row)

    async def open(self, opening: SessionOpening) -> None:
        """Open the session through the definer. A refusal writes nothing."""
        try:
            await self._fetch_one(
                self._OPEN,
                {
                    "session_id": str(opening.session_id),
                    "learner_id": str(opening.learner_id),
                    "tutor_id": self._sealed.seal_text(opening.tutor_id),
                    "started_at": opening.started_at,
                },
            )
        except Exception as exc:
            if self._raised_sqlstate(exc, OpenSessionFunction.SQLSTATE):
                msg = "learner is not known, or their retention has ended"
                raise SessionOpenRejected(msg) from exc
            raise

    async def learners(self) -> tuple[LearnerSummary, ...]:
        """Return each learner id and whether retention still holds."""
        now = self._clock.now()
        rows = await self._fetch_all(self._LEARNERS)
        return tuple(
            LearnerSummary(
                learner_id=self._uuid(row[0]),
                retained=self._instant(row[1]) > now,
            )
            for row in rows
        )

    def _summary(self, row: tuple[object, ...]) -> SessionSummary:
        stopped = self._optional_instant(row[3])
        return SessionSummary(
            session_id=self._uuid(row[0]),
            learner_id=self._uuid(row[1]),
            started_at=self._instant(row[2]),
            stopped_at=stopped,
            open=stopped is None,
        )
