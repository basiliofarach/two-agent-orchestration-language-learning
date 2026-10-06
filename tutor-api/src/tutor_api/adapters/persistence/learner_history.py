"""Read allowlisted learner history on the request connection (REQ-HISTORY)."""

from datetime import datetime

from tutor_core.domain.models.learner import (
    HistoryFieldSet,
    HistoryItem,
    LearnerHistorySnapshot,
    LearnerId,
)
from tutor_core.domain.ports.cipher import CipherPort
from tutor_core.domain.ports.clock import ClockPort
from tutor_core.domain.ports.learner_history import LearnerHistoryPort
from tutor_core.domain.ports.unit_of_work import TransactionConnection


class HistoryOutcomeCodec:
    """Seal an item outcome as one byte, so both outcomes seal to one length.

    AES-GCM preserves plaintext length. Sealing ``"true"`` and ``"false"``
    would leave a 4-byte and a 5-byte ciphertext, and anyone who can read
    the column would read the outcome from its length (DEC-0012). One byte
    each, ``0x01`` and ``0x00``, closes that.
    """

    _CORRECT = b"\x01"
    _INCORRECT = b"\x00"

    def encode(self, correct: bool) -> bytes:
        """The plaintext to seal for ``correct``."""
        return self._CORRECT if correct else self._INCORRECT

    def decode(self, opened: bytes) -> bool:
        """The outcome an opened envelope holds. Anything else raises."""
        if opened == self._CORRECT:
            return True
        if opened == self._INCORRECT:
            return False
        msg = "history outcome is not one outcome byte"
        raise ValueError(msg)


class PostgresLearnerHistory(LearnerHistoryPort):
    """Read history. There is no insert, update or delete.

    ``allowlist`` is the deployment's field set, fixed at construction. A
    read selects only the fields the turn requested, and a requested field
    outside the allowlist raises rather than being read or dropped. The
    database grant is column-level too: the application role cannot select
    ``pseudonym`` at all (REQ-HISTORY).

    Retention is applied before any history column is selected. A learner
    whose ``retain_until`` has passed yields an empty snapshot, even
    though the rows are still there (REQ-MINOR). ``retain_until`` is
    selected first because the check cannot run without it; it is not a
    history field and it is not returned.

    Events are ordered by ``occurred_at``, then by ``id``. The prototype
    seed writes several events at one instant; without the id the prompt
    could list them in a different order on the next run.
    """

    _RETENTION = """
        SELECT retain_until
        FROM learner
        WHERE learner_id = :learner_id
        """

    _PROFICIENCY = """
        SELECT proficiency_level
        FROM learner
        WHERE learner_id = :learner_id
        """

    _EVENTS = """
        SELECT item_id, correct, occurred_at
        FROM learner_history_event
        WHERE learner_id = :learner_id
        ORDER BY occurred_at, id
        """

    def __init__(
        self,
        connection: TransactionConnection,
        cipher: CipherPort,
        clock: ClockPort,
        allowlist: HistoryFieldSet,
        outcomes: HistoryOutcomeCodec,
    ) -> None:
        self._connection = connection
        self._cipher = cipher
        self._clock = clock
        self._allowlist = allowlist
        self._outcomes = outcomes

    async def read(
        self,
        learner_id: LearnerId,
        requested: HistoryFieldSet,
    ) -> LearnerHistorySnapshot:
        """Return the requested fields, or an empty snapshot when retention ended."""
        outside = self._allowlist.outside(requested.fields)
        if outside:
            msg = f"history fields outside the allowlist: {', '.join(outside)}"
            raise ValueError(msg)
        retained = await self._retained(learner_id)
        if not retained:
            return self._empty(learner_id)
        proficiency = await self._proficiency(learner_id, requested)
        events = await self._events(learner_id, requested)
        return LearnerHistorySnapshot(
            learner_id=learner_id,
            proficiency_level=proficiency,
            events=events,
        )

    async def _retained(self, learner_id: LearnerId) -> bool:
        row = await self._connection.fetch_one(
            self._RETENTION,
            {"learner_id": learner_id.value},
        )
        if row is None:
            msg = "learner is not known"
            raise ValueError(msg)
        return self._timestamp(row[0]) > self._clock.now()

    async def _proficiency(
        self, learner_id: LearnerId, requested: HistoryFieldSet
    ) -> str | None:
        if not requested.admits("proficiency_level"):
            return None
        row = await self._connection.fetch_one(
            self._PROFICIENCY,
            {"learner_id": learner_id.value},
        )
        if row is None:
            msg = "learner is not known"
            raise ValueError(msg)
        return self._cipher.decrypt(self._bytes(row[0])).decode("utf-8")

    async def _events(
        self, learner_id: LearnerId, requested: HistoryFieldSet
    ) -> tuple[HistoryItem, ...] | None:
        if not requested.admits("events"):
            return None
        rows = await self._connection.fetch_all(
            self._EVENTS,
            {"learner_id": learner_id.value},
        )
        return tuple(self._event(row) for row in rows)

    def _event(self, row: tuple[object, ...]) -> HistoryItem:
        return HistoryItem(
            item_id=self._cipher.decrypt(self._bytes(row[0])).decode("utf-8"),
            correct=self._outcomes.decode(self._cipher.decrypt(self._bytes(row[1]))),
            occurred_at=self._timestamp(row[2]),
        )

    def _empty(self, learner_id: LearnerId) -> LearnerHistorySnapshot:
        return LearnerHistorySnapshot(
            learner_id=learner_id,
            proficiency_level=None,
            events=None,
        )

    def _timestamp(self, value: object) -> datetime:
        if isinstance(value, datetime):
            if value.utcoffset() is None:
                msg = "timestamp must be timezone-aware"
                raise ValueError(msg)
            return value
        msg = "timestamp is missing"
        raise ValueError(msg)

    def _bytes(self, value: object) -> bytes:
        if isinstance(value, bytes):
            return value
        if isinstance(value, bytearray | memoryview):
            return bytes(value)
        msg = "history value is not ciphertext"
        raise ValueError(msg)
