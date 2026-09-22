"""PostgresAuditSink writes one chained record and nothing else."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from tests.support.samples import Samples
from tests.support.sealed_turn import SealedTurn
from tests.unit.adapters.test_unit_of_work import RecordingConnection

from tutor_api.adapters.frozen_clock import FrozenClock
from tutor_api.adapters.persistence.audit_sink import (
    AuditAppendRejected,
    PostgresAuditSink,
)
from tutor_core.domain.audit.record_hash import AuditRecordHash
from tutor_core.domain.models.audit import TurnAuditRecord
from tutor_core.domain.ports.cipher import CipherPort


class ReversibleCipher(CipherPort):
    """Prefix the plaintext so a unit test can read the bound parameter."""

    def encrypt(self, plaintext: bytes) -> bytes:
        return b"sealed:" + plaintext

    def decrypt(self, envelope: bytes) -> bytes:
        return envelope.removeprefix(b"sealed:")


class BoundSink:
    """A sink and the connection it was given."""

    def __init__(self, rows: tuple[tuple[object, ...], ...] = ()) -> None:
        self.connection = RecordingConnection()
        # The session lock is the first fetch. It must not consume the
        # predecessor row the test queued.
        self.connection.rows.append(("held",))
        self.connection.rows.extend(rows)
        self.hasher = AuditRecordHash()
        self.cipher = ReversibleCipher()
        self.sink = PostgresAuditSink(self.connection, self.cipher, self.hasher)

    def seal(self, record: TurnAuditRecord, previous: str) -> TurnAuditRecord:
        return SealedTurn(self.hasher).at(record, previous)


class TestPostgresAuditSink:
    def test_append_is_the_only_write_method_exposed(self) -> None:
        public = [
            name
            for name in dir(PostgresAuditSink)
            if not name.startswith("_") and callable(getattr(PostgresAuditSink, name))
        ]
        assert public == ["append"]

    async def test_recorded_at_comes_from_injected_clock(self) -> None:
        clock = FrozenClock(datetime(2026, 9, 21, 15, 30, tzinfo=UTC))
        bound = BoundSink()
        record = bound.seal(
            Samples()
            .stopped_audit_record()
            .model_copy(update={"recorded_at": clock.now()}),
            AuditRecordHash.GENESIS,
        )
        await bound.sink.append(record)
        assert bound.connection.parameters[0]["recorded_at"] == clock.now()
        assert bound.connection.statements[0].lstrip().upper().startswith("INSERT")

    async def test_a_stop_writes_null_generation_and_no_citation(self) -> None:
        bound = BoundSink()
        record = bound.seal(Samples().stopped_audit_record(), AuditRecordHash.GENESIS)
        await bound.sink.append(record)
        parameters = bound.connection.parameters[0]
        assert parameters["model_revision"] is None
        assert parameters["template_version"] is None
        assert parameters["decoding_params"] is None
        assert parameters["output_before_checks"] is None
        assert parameters["output_after_checks"] is None
        assert parameters["ai_disclosure"] is None
        assert parameters["refused"] is None
        assert parameters["safety_flags"] is None
        assert parameters["source_support"] is None
        assert len(bound.connection.statements) == 1
        prompt = bound.cipher.decrypt(parameters["learner_prompt_redacted"])
        assert prompt == record.learner_prompt_redacted.encode("utf-8")

    async def test_a_generated_turn_encrypts_outputs_and_cites_the_chunk(self) -> None:
        bound = BoundSink()
        chunk_id = "00000000-0000-4000-8000-000000000061"
        record = bound.seal(
            Samples()
            .audit_record()
            .model_copy(update={"retrieved_context_ids": (chunk_id,)}),
            AuditRecordHash.GENESIS,
        )
        await bound.sink.append(record)
        turn = bound.connection.parameters[0]
        citation = bound.connection.parameters[1]
        assert turn["model_revision"] == "b" * 40
        assert turn["refused"] is False
        assert bound.cipher.decrypt(turn["template_version"]) == b"tpl-1"
        assert b'"temperature":0.0' in bound.cipher.decrypt(turn["decoding_params"])
        assert citation == {
            "turn_id": record.turn_id,
            "chunk_id": UUID(chunk_id),
            "ordinal": 0,
        }
        assert all(
            statement.lstrip().upper().startswith("INSERT")
            for statement in bound.connection.statements
        )

    async def test_a_mismatched_digest_writes_nothing(self) -> None:
        bound = BoundSink()
        record = Samples().stopped_audit_record()
        with pytest.raises(AuditAppendRejected, match="canonical digest"):
            await bound.sink.append(record)
        assert bound.connection.statements == []
        assert bound.connection.fetches == []

    async def test_the_first_record_must_chain_to_genesis(self) -> None:
        bound = BoundSink()
        record = bound.seal(Samples().stopped_audit_record(), "c" * 64)
        with pytest.raises(AuditAppendRejected, match="genesis hash"):
            await bound.sink.append(record)
        assert bound.connection.statements == []
        assert bound.connection.fetches

    async def test_the_first_record_must_be_turn_index_zero(self) -> None:
        bound = BoundSink()
        record = bound.seal(
            Samples().stopped_audit_record().model_copy(update={"turn_index": 1}),
            AuditRecordHash.GENESIS,
        )
        with pytest.raises(AuditAppendRejected, match="turn index 0"):
            await bound.sink.append(record)
        assert bound.connection.statements == []

    async def test_a_later_record_must_continue_the_previous_hash(self) -> None:
        first = SealedTurn(AuditRecordHash()).at(
            Samples().stopped_audit_record(), AuditRecordHash.GENESIS
        )
        bound = BoundSink(rows=((first.record_hash, 0),))
        record = bound.seal(
            Samples()
            .stopped_audit_record()
            .model_copy(
                update={
                    "turn_id": UUID("00000000-0000-4000-8000-000000000013"),
                    "turn_index": 1,
                }
            ),
            AuditRecordHash.GENESIS,
        )
        with pytest.raises(AuditAppendRejected, match="previous record hash"):
            await bound.sink.append(record)
        assert bound.connection.statements == []

    async def test_a_later_record_must_continue_the_turn_index(self) -> None:
        hasher = AuditRecordHash()
        first = SealedTurn(hasher).at(
            Samples().stopped_audit_record(), AuditRecordHash.GENESIS
        )
        bound = BoundSink(rows=((first.record_hash, 0),))
        record = bound.seal(
            Samples()
            .stopped_audit_record()
            .model_copy(
                update={
                    "turn_id": UUID("00000000-0000-4000-8000-000000000013"),
                    "turn_index": 2,
                }
            ),
            first.record_hash,
        )
        with pytest.raises(AuditAppendRejected, match="turn index does not"):
            await bound.sink.append(record)

    async def test_append_locks_the_session_before_reading_the_predecessor(
        self,
    ) -> None:
        bound = BoundSink()
        record = bound.seal(Samples().stopped_audit_record(), AuditRecordHash.GENESIS)
        await bound.sink.append(record)
        lock, predecessor = bound.connection.fetches
        assert "pg_advisory_xact_lock" in lock[0]
        assert lock[1] == {
            "namespace": PostgresAuditSink._CHAIN_LOCK_NAMESPACE,
            "session_id": str(record.session_id),
        }
        assert "FROM turn_audit" in predecessor[0]
        assert predecessor[1] == {"session_id": record.session_id}

    async def test_a_later_record_appends_when_the_link_holds(self) -> None:
        hasher = AuditRecordHash()
        first = SealedTurn(hasher).at(
            Samples().stopped_audit_record(), AuditRecordHash.GENESIS
        )
        bound = BoundSink(rows=((first.record_hash, 0),))
        record = bound.seal(
            Samples()
            .stopped_audit_record()
            .model_copy(
                update={
                    "turn_id": UUID("00000000-0000-4000-8000-000000000013"),
                    "turn_index": 1,
                }
            ),
            first.record_hash,
        )
        await bound.sink.append(record)
        assert bound.connection.parameters[0]["previous_record_hash"] == (
            first.record_hash
        )
        assert bound.connection.parameters[0]["turn_index"] == 1
