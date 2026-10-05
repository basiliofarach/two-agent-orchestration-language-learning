"""Redacted learner text is what the audit row stores."""

import json
from uuid import UUID

import psycopg
from tests.support.curation import Curator
from tests.support.migrated_database import MigratedDatabase, PostgresUrl
from tests.support.samples import Samples
from tests.support.sealed_turn import SealedTurn

from tutor_api.adapters.checks.pii_redaction import (
    RegexPiiRedactor,
    StandardPiiSteps,
)
from tutor_api.adapters.persistence.aes_gcm_envelope import AesGcmEnvelope
from tutor_api.adapters.persistence.audit_sink import PostgresAuditSink
from tutor_api.adapters.persistence.database import DatabaseEngine
from tutor_api.adapters.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tutor_core.domain.audit.record_hash import AuditRecordHash
from tutor_core.domain.models.audit import TurnAuditRecord
from tutor_core.domain.models.safety import StoredLearnerPrompt
from tutor_core.domain.ports.audit_sink import AuditSinkPort
from tutor_core.domain.ports.unit_of_work import (
    TransactionalWork,
    TransactionConnection,
)


class AppendTurn(TransactionalWork):
    def __init__(self, sink: AuditSinkPort, record: TurnAuditRecord) -> None:
        self._sink = sink
        self._record = record

    async def run(self, connection: TransactionConnection) -> None:
        await self._sink.append(self._record)


class TestPiiRedactionAudit:
    async def test_no_unredacted_learner_text_reaches_the_audit_log(
        self, fresh_database: str
    ) -> None:
        cipher = AesGcmEnvelope(key=bytes(range(32)), key_id=UUID(int=1))
        database = MigratedDatabase()
        database.upgrade(fresh_database)
        database.seed_learner(fresh_database)
        await Curator(PostgresUrl(fresh_database).async_url(), cipher).publish(
            Samples().policy_card(),
            Samples().when(),
        )
        raw = "Email ada@example.com about the library"
        redacted = RegexPiiRedactor(StandardPiiSteps().steps()).redact(raw)
        hasher = AuditRecordHash()
        record = SealedTurn(hasher).at(
            Samples()
            .stopped_audit_record()
            .model_copy(
                update={
                    "learner_prompt": StoredLearnerPrompt.model_validate(redacted),
                }
            ),
            AuditRecordHash.GENESIS,
        )
        engine = DatabaseEngine(
            fresh_database.replace("postgresql://", "postgresql+asyncpg://", 1)
        )
        enlisted = await engine.connect()
        try:
            sink = PostgresAuditSink(enlisted, cipher, hasher)
            await SqlAlchemyUnitOfWork(enlisted).run(AppendTurn(sink, record))
        finally:
            await engine.dispose()
        with psycopg.connect(fresh_database) as opened, opened.cursor() as cursor:
            cursor.execute(
                """
                SELECT learner_prompt_redacted, redacted_categories
                FROM turn_audit
                """
            )
            row = cursor.fetchone()
        assert row is not None
        prompt = cipher.decrypt(bytes(row[0])).decode("utf-8")
        categories = json.loads(cipher.decrypt(bytes(row[1])))
        assert "ada@example.com" not in prompt
        assert "[REDACTED:email]" in prompt
        assert categories == ["email"]
