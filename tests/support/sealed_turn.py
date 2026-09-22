"""A turn record whose stored hash is the canonical digest."""

from tutor_core.domain.audit.record_hash import AuditRecordHash
from tutor_core.domain.models.audit import TurnAuditRecord


class SealedTurn:
    """Copy a record onto a predecessor and set ``record_hash`` to its digest."""

    def __init__(self, hasher: AuditRecordHash) -> None:
        self._hasher = hasher

    def at(self, record: TurnAuditRecord, previous: str) -> TurnAuditRecord:
        drafted = record.model_copy(
            update={
                "previous_record_hash": previous,
                "record_hash": "0" * 64,
            }
        )
        return drafted.model_copy(update={"record_hash": self._hasher.digest(drafted)})
