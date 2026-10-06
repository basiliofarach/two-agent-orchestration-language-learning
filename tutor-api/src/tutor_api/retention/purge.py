"""Delete personal history once ``retain_until`` has passed, and log it."""

from collections.abc import Mapping
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from tutor_core.domain.models.timestamps import AwareDatetime, Timestamped
from tutor_core.domain.ports.cipher import CipherPort
from tutor_core.domain.ports.clock import ClockPort
from tutor_core.domain.ports.unit_of_work import (
    TransactionalWork,
    TransactionConnection,
)


class PurgeReceipt(Timestamped):
    """One learner whose personal rows were removed (REQ-MINOR)."""

    learner_id: UUID
    history_rows: int = Field(ge=0)
    sessions_stopped: int = Field(ge=0)
    purged_at: AwareDatetime


class PurgeLog(BaseModel):
    """What one run purged. Filled inside the transaction."""

    model_config = ConfigDict(extra="forbid")

    receipts: tuple[PurgeReceipt, ...] = ()


class RetentionPurge(TransactionalWork):
    """Purge learners past ``retain_until`` and append a log row for each.

    History reads already return nothing once the instant has passed. This
    job removes the event rows, replaces the sealed pseudonym and
    proficiency with a tombstone, and stops any session still open for the
    learner, so no new turn can be conducted for them. ``open_session``
    already refuses them a new one. The learner id stays: sessions and the
    audit chain reference it, and those tables are append-only (REQ-AUDIT).

    A learner already in ``retention_purge`` is skipped, so running the job
    twice logs nothing the second time.

    It runs as the database owner on the operator path, in a unit of work
    like the prototype seed (DEC-0014). The request role cannot delete.

    What it does not remove: ``turn_audit`` keeps the redacted prompts and
    history snapshots of turns already taken. Those rows are the Article 12
    log, which is retained for its own period; they are redacted and
    sealed, and a learner's id in them is pseudonymous (DEC-0012).
    """

    _TOMBSTONE = "purged"

    _DUE = """
        SELECT learner.learner_id
        FROM learner
        WHERE learner.retain_until <= :now
          AND NOT EXISTS (
              SELECT 1 FROM retention_purge AS purge
              WHERE purge.learner_id = learner.learner_id
          )
        ORDER BY learner.learner_id
        """

    _COUNT = """
        SELECT count(*)
        FROM learner_history_event
        WHERE learner_id = :learner_id
        """

    _DELETE_EVENTS = """
        DELETE FROM learner_history_event
        WHERE learner_id = :learner_id
        """

    _TOMBSTONE_LEARNER = """
        UPDATE learner
        SET pseudonym = :sealed, proficiency_level = :sealed
        WHERE learner_id = :learner_id
        """

    _OPEN_SESSIONS = """
        SELECT count(*)
        FROM tutoring_session
        WHERE learner_id = :learner_id AND stopped_at IS NULL
        """

    _STOP_SESSIONS = """
        UPDATE tutoring_session
        SET stopped_at = :now, stop_reason = :reason
        WHERE learner_id = :learner_id AND stopped_at IS NULL
        """

    _LOG = """
        INSERT INTO retention_purge (id, learner_id, purged_at, history_rows)
        VALUES (:id, :learner_id, :now, :history_rows)
        """

    def __init__(self, cipher: CipherPort, clock: ClockPort, log: PurgeLog) -> None:
        self._cipher = cipher
        self._clock = clock
        self._log = log

    async def run(self, connection: TransactionConnection) -> None:
        """Purge every due learner on the owner's connection."""
        now = self._clock.now()
        due = await connection.fetch_all(self._DUE, {"now": now})
        receipts: list[PurgeReceipt] = []
        for row in due:
            learner_id = row[0] if isinstance(row[0], UUID) else UUID(str(row[0]))
            receipts.append(await self._purge(connection, learner_id, now))
        self._log.receipts = tuple(receipts)

    async def _purge(
        self,
        connection: TransactionConnection,
        learner_id: UUID,
        now: AwareDatetime,
    ) -> PurgeReceipt:
        key = {"learner_id": learner_id}
        rows = await self._count(connection, self._COUNT, key)
        sessions = await self._count(connection, self._OPEN_SESSIONS, key)
        await connection.execute(self._DELETE_EVENTS, key)
        await connection.execute(
            self._TOMBSTONE_LEARNER, {**key, "sealed": self._seal(self._TOMBSTONE)}
        )
        await connection.execute(
            self._STOP_SESSIONS,
            {**key, "now": now, "reason": self._seal("retention purge")},
        )
        await connection.execute(
            self._LOG, {**key, "id": uuid4(), "now": now, "history_rows": rows}
        )
        return PurgeReceipt(
            learner_id=learner_id,
            history_rows=rows,
            sessions_stopped=sessions,
            purged_at=now,
        )

    async def _count(
        self,
        connection: TransactionConnection,
        statement: str,
        parameters: Mapping[str, object],
    ) -> int:
        row = await connection.fetch_one(statement, parameters)
        return 0 if row is None else int(str(row[0]))

    def _seal(self, text: str) -> bytes:
        return self._cipher.encrypt(text.encode("utf-8"))
