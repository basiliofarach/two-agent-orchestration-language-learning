"""Delete personal history once ``retain_until`` has passed, and log it."""

from uuid import UUID, uuid4

import psycopg

from tutor_core.domain.models.timestamps import AwareDatetime, Timestamped
from tutor_core.domain.ports.cipher import CipherPort
from tutor_core.domain.ports.clock import ClockPort


class PurgeReceipt(Timestamped):
    """One learner whose personal rows were removed (REQ-MINOR)."""

    learner_id: UUID
    history_rows: int
    purged_at: AwareDatetime


class RetentionPurge:
    """Purge learners past ``retain_until`` and append a log row.

    History reads already return nothing once the instant has passed. This
    job removes the event rows and replaces the sealed pseudonym and
    proficiency with a tombstone, so the personal text is gone. The
    learner id stays: sessions and the audit chain reference it, and those
    tables are append-only (REQ-AUDIT). The job runs as the database owner.
    The request role cannot delete.
    """

    _TOMBSTONE = "purged"

    _DUE = """
        SELECT learner_id
        FROM learner
        WHERE retain_until <= %s
        """

    _COUNT = """
        SELECT count(*)
        FROM learner_history_event
        WHERE learner_id = %s
        """

    _DELETE_EVENTS = """
        DELETE FROM learner_history_event
        WHERE learner_id = %s
        """

    _TOMBSTONE_LEARNER = """
        UPDATE learner
        SET pseudonym = %s, proficiency_level = %s
        WHERE learner_id = %s
        """

    _LOG = """
        INSERT INTO retention_purge (id, learner_id, purged_at, history_rows)
        VALUES (%s, %s, %s, %s)
        """

    def __init__(self, cipher: CipherPort, clock: ClockPort) -> None:
        self._cipher = cipher
        self._clock = clock

    def run(self, url: str) -> tuple[PurgeReceipt, ...]:
        """Purge every due learner on ``url`` and return what was logged."""
        now = self._clock.now()
        sealed = self._cipher.encrypt(self._TOMBSTONE.encode("utf-8"))
        receipts: list[PurgeReceipt] = []
        with psycopg.connect(url) as connection:
            due = connection.execute(self._DUE, (now,)).fetchall()
            for (learner_id,) in due:
                receipts.append(self._purge(connection, learner_id, now, sealed))
        return tuple(receipts)

    def _purge(
        self,
        connection: psycopg.Connection,
        learner_id: object,
        now: AwareDatetime,
        sealed: bytes,
    ) -> PurgeReceipt:
        identifier = learner_id
        if not isinstance(identifier, UUID):
            identifier = UUID(str(learner_id))
        count = connection.execute(self._COUNT, (identifier,)).fetchone()
        rows = 0 if count is None else int(count[0])
        connection.execute(self._DELETE_EVENTS, (identifier,))
        connection.execute(self._TOMBSTONE_LEARNER, (sealed, sealed, identifier))
        connection.execute(self._LOG, (uuid4(), identifier, now, rows))
        return PurgeReceipt(
            learner_id=identifier,
            history_rows=rows,
            purged_at=now,
        )
