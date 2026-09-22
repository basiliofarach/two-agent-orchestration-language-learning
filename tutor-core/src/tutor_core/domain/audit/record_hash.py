"""Canonical digest of one turn record (REQ-AUDIT)."""

import hashlib
import json

from tutor_core.domain.models.audit import TurnAuditRecord


class AuditRecordHash:
    """SHA-256 of the canonical turn record.

    ``GENESIS`` is the predecessor of the first record in a session. It is
    64 hex zeros: the same width as a digest, and not the hash of a record.
    A later record's ``previous_record_hash`` is its predecessor's
    ``record_hash``.

    The digest excludes ``record_hash`` itself and includes every other
    field. Generation fields that are absent stay in the payload as null.
    A later human action is not on this record, so it is not part of the
    turn hash.
    """

    GENESIS = "0" * 64

    def digest(self, record: TurnAuditRecord) -> str:
        """Return the hex digest of ``canonical(record)``."""
        payload = self.canonical(record).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def canonical(self, record: TurnAuditRecord) -> str:
        """Return the JSON whose digest is ``record_hash``.

        Keys are sorted and separators carry no whitespace, so two equal
        records produce one string. Absent generation fields are null, not
        omitted.
        """
        payload = record.model_dump(mode="json", exclude={"record_hash"})
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
