"""Append one turn record on the enlisted connection (REQ-AUDIT)."""

import json
from uuid import UUID

from tutor_core.domain.audit.record_hash import AuditRecordHash
from tutor_core.domain.models.audit import TurnAuditRecord
from tutor_core.domain.ports.audit_sink import AuditSinkPort
from tutor_core.domain.ports.cipher import CipherPort
from tutor_core.domain.ports.unit_of_work import TransactionConnection


class AuditAppendRejected(Exception):
    """The record does not continue this session's hash chain."""


class PostgresAuditSink(AuditSinkPort):
    """Write ``turn_audit`` and its citations on a connection the caller holds.

    The caller constructs this sink with the connection the unit of work
    will commit. This class does not open one. A rejected record raises
    before any insert, and a later failure on that same connection rolls
    the insert back with the work it describes.

    Appends for one session take a transaction advisory lock before the
    predecessor read. The lock releases when that transaction commits or
    rolls back, so a second append waits and then links to the row the
    first one wrote. ``turn_audit_session_turn`` is the uniqueness backstop.

    ``recorded_at`` is taken from the record. This class does not read a
    clock.
    """

    _TURN = """
        INSERT INTO turn_audit (
            turn_id, session_id, turn_index,
            learner_prompt_redacted, redacted_categories,
            model_revision, template_version, decoding_params,
            output_before_checks, output_after_checks, ai_disclosure,
            refused, safety_flags, source_support,
            policy_version, previous_record_hash, record_hash, recorded_at
        ) VALUES (
            :turn_id, :session_id, :turn_index,
            :learner_prompt_redacted, :redacted_categories,
            :model_revision, :template_version, :decoding_params,
            :output_before_checks, :output_after_checks, :ai_disclosure,
            :refused, :safety_flags, :source_support,
            :policy_version, :previous_record_hash, :record_hash, :recorded_at
        )
        """

    _CITATION = """
        INSERT INTO turn_citation (turn_id, chunk_id, ordinal)
        VALUES (:turn_id, :chunk_id, :ordinal)
        """

    # First key of pg_advisory_xact_lock. The second is hashtext(session_id).
    # Another subsystem that takes a transaction advisory lock must use a
    # different first key, or it queues behind an audit append.
    _CHAIN_LOCK_NAMESPACE = 4812

    _LOCK_SESSION = """
        SELECT pg_advisory_xact_lock(
            :namespace, hashtext(CAST(:session_id AS text))
        )
        """

    _PREDECESSOR = """
        SELECT record_hash, turn_index
        FROM turn_audit
        WHERE session_id = :session_id
        ORDER BY turn_index DESC
        LIMIT 1
        """

    def __init__(
        self,
        connection: TransactionConnection,
        cipher: CipherPort,
        hasher: AuditRecordHash,
    ) -> None:
        self._connection = connection
        self._cipher = cipher
        self._hasher = hasher

    async def append(self, record: TurnAuditRecord) -> None:
        """Append ``record`` and one citation row per retrieved chunk."""
        self._require_digest(record)
        await self._lock_session(record)
        await self._require_predecessor(record)
        await self._connection.execute(self._TURN, self._turn_parameters(record))
        for ordinal, chunk_id in enumerate(record.retrieved_context_ids):
            await self._connection.execute(
                self._CITATION,
                {
                    "turn_id": record.turn_id,
                    "chunk_id": UUID(chunk_id),
                    "ordinal": ordinal,
                },
            )

    def _require_digest(self, record: TurnAuditRecord) -> None:
        if record.record_hash != self._hasher.digest(record):
            msg = "record hash does not match the canonical digest"
            raise AuditAppendRejected(msg)

    async def _lock_session(self, record: TurnAuditRecord) -> None:
        await self._connection.fetch_one(
            self._LOCK_SESSION,
            {
                "namespace": self._CHAIN_LOCK_NAMESPACE,
                "session_id": str(record.session_id),
            },
        )

    async def _require_predecessor(self, record: TurnAuditRecord) -> None:
        row = await self._connection.fetch_one(
            self._PREDECESSOR,
            {"session_id": record.session_id},
        )
        if row is None:
            self._require_genesis(record)
            return
        self._require_link(record, row)

    def _require_genesis(self, record: TurnAuditRecord) -> None:
        if record.previous_record_hash != AuditRecordHash.GENESIS:
            msg = "the first record in a session chains to the genesis hash"
            raise AuditAppendRejected(msg)
        if record.turn_index != 0:
            msg = "the first record in a session is turn index 0"
            raise AuditAppendRejected(msg)

    def _require_link(self, record: TurnAuditRecord, row: tuple[object, ...]) -> None:
        previous = str(row[0])
        expected_index = int(str(row[1])) + 1
        if record.previous_record_hash != previous:
            msg = "previous record hash does not continue the session chain"
            raise AuditAppendRejected(msg)
        if record.turn_index != expected_index:
            msg = "turn index does not continue the session chain"
            raise AuditAppendRejected(msg)

    def _turn_parameters(self, record: TurnAuditRecord) -> dict[str, object]:
        payload = record.model_dump(mode="json")
        return {
            "turn_id": record.turn_id,
            "session_id": record.session_id,
            "turn_index": record.turn_index,
            "learner_prompt_redacted": self._text(payload["learner_prompt_redacted"]),
            "redacted_categories": self._json(payload["redacted_categories"]),
            "model_revision": record.model_revision,
            "template_version": self._optional_text(payload["template_version"]),
            "decoding_params": self._optional_json(payload["decoding_params"]),
            "output_before_checks": self._optional_text(
                payload["output_before_checks"]
            ),
            "output_after_checks": self._optional_text(payload["output_after_checks"]),
            "ai_disclosure": self._optional_text(payload["ai_disclosure"]),
            "refused": record.refused,
            "safety_flags": self._optional_json(payload["safety_flags"]),
            "source_support": self._optional_json(payload["source_support"]),
            "policy_version": record.policy_version,
            "previous_record_hash": record.previous_record_hash,
            "record_hash": record.record_hash,
            "recorded_at": record.recorded_at,
        }

    def _text(self, value: object) -> bytes:
        return self._cipher.encrypt(str(value).encode("utf-8"))

    def _json(self, value: object) -> bytes:
        return self._cipher.encrypt(self._canonical_json(value))

    def _optional_text(self, value: object) -> bytes | None:
        if value is None:
            return None
        return self._text(value)

    def _optional_json(self, value: object) -> bytes | None:
        if value is None:
            return None
        return self._json(value)

    def _canonical_json(self, value: object) -> bytes:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
