"""Walk a session's records and name the one that breaks the chain."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from tutor_core.domain.audit.record_hash import AuditRecordHash
from tutor_core.domain.models.audit import TurnAuditRecord


class ChainBreak(BaseModel):
    """The record that no longer continues the chain (REQ-AUDIT).

    ``excised`` means this record's ``previous_record_hash`` is not the
    predecessor's ``record_hash`` (or the genesis value, for the first
    record). The missing record is gone, so the report names the record
    that no longer links. ``tampered`` means the link holds and the stored
    ``record_hash`` is not the digest of this record.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    turn_id: UUID
    reason: Literal["tampered", "excised"]


class ChainVerifier:
    """Check a session's records in the order they were appended."""

    def __init__(self, hasher: AuditRecordHash) -> None:
        self._hasher = hasher

    def find_break(self, records: tuple[TurnAuditRecord, ...]) -> ChainBreak | None:
        """Return the first break, or ``None`` when the chain holds."""
        previous = AuditRecordHash.GENESIS
        for record in records:
            if record.previous_record_hash != previous:
                return ChainBreak(turn_id=record.turn_id, reason="excised")
            if record.record_hash != self._hasher.digest(record):
                return ChainBreak(turn_id=record.turn_id, reason="tampered")
            previous = record.record_hash
        return None
