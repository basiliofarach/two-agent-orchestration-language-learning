"""The audit row and the work it describes commit, or roll back, together."""

import asyncio
from pathlib import Path
from uuid import UUID

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from tests.support.samples import Samples
from tests.support.sealed_turn import SealedTurn

from tutor_api.adapters.persistence.aes_gcm_envelope import AesGcmEnvelope
from tutor_api.adapters.persistence.audit_sink import (
    AuditAppendRejected,
    PostgresAuditSink,
)
from tutor_api.adapters.persistence.database import DatabaseEngine
from tutor_api.adapters.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tutor_core.domain.audit.chain import ChainVerifier
from tutor_core.domain.audit.record_hash import AuditRecordHash
from tutor_core.domain.models.audit import TurnAuditRecord
from tutor_core.domain.ports.audit_sink import AuditSinkPort
from tutor_core.domain.ports.cipher import CipherPort
from tutor_core.domain.ports.unit_of_work import (
    TransactionalWork,
    TransactionConnection,
)

_LEARNER = "00000000-0000-4000-8000-000000000001"
_SESSION = "00000000-0000-4000-8000-000000000004"
_DOCUMENT = "00000000-0000-4000-8000-000000000060"
_CHUNK = "00000000-0000-4000-8000-000000000061"
_SECOND_TURN = UUID("00000000-0000-4000-8000-000000000013")


class PostgresUrl:
    """The driver flavours one database is reached by."""

    def __init__(self, plain: str) -> None:
        self._plain = plain

    def sync(self) -> str:
        return self._plain.replace("postgresql://", "postgresql+psycopg://", 1)

    def async_url(self) -> str:
        return self._plain.replace("postgresql://", "postgresql+asyncpg://", 1)


class AlembicRunner:
    def __init__(self, url: str) -> None:
        root = Path(__file__).resolve().parents[2] / "tutor-api"
        self._config = Config(str(root / "alembic.ini"))
        self._config.set_main_option("script_location", str(root / "alembic"))
        self._config.set_main_option("sqlalchemy.url", url)

    def upgrade(self) -> None:
        command.upgrade(self._config, "head")


class Catalogue:
    """Learner, session, policy, and one chunk the citation can reference."""

    def install(self, url: str, with_probe: bool) -> None:
        AlembicRunner(PostgresUrl(url).sync()).upgrade()
        envelope = b"\x01" + b"\x00" * 44
        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO learner (
                    learner_id, pseudonym, proficiency_level, retain_until
                ) VALUES (%s, %s, %s, '2026-12-01T00:00:00Z')
                """,
                (_LEARNER, envelope, envelope),
            )
            cursor.execute(
                """
                INSERT INTO tutoring_session (
                    id, tutor_id, learner_id, started_at
                ) VALUES (%s, %s, %s, '2026-01-01T00:00:00Z')
                """,
                (_SESSION, envelope, _LEARNER),
            )
            cursor.execute(
                """
                INSERT INTO policy_version (
                    version, allowed_actions, denied_actions, escalation_rules,
                    article_mappings, effective_from
                ) VALUES ('policy-1', %s, %s, %s, %s, '2026-01-01T00:00:00Z')
                """,
                (envelope, envelope, envelope, envelope),
            )
            cursor.execute(
                """
                INSERT INTO kb_document (id, source_uri, version, review_status)
                VALUES (%s, 'kb://library', '1', 'approved')
                """,
                (_DOCUMENT,),
            )
            cursor.execute(
                """
                INSERT INTO kb_chunk (
                    id, document_id, ordinal, content, embedding
                ) VALUES (%s, %s, 0, %s, %s)
                """,
                (
                    _CHUNK,
                    _DOCUMENT,
                    envelope,
                    "[" + ",".join(["0"] * 768) + "]",
                ),
            )
            if with_probe:
                cursor.execute("CREATE TABLE described_work (id integer PRIMARY KEY)")


class DescribedTurn(TransactionalWork):
    """The audit row and one other write, on the connection the sink holds."""

    def __init__(self, sink: AuditSinkPort, record: TurnAuditRecord) -> None:
        self._sink = sink
        self._record = record

    async def run(self, connection: TransactionConnection) -> None:
        await connection.execute("INSERT INTO described_work (id) VALUES (1)")
        await self._sink.append(self._record)


class AbortedTurn(TransactionalWork):
    """Writes the audit row, then fails, so the unit of work rolls both back."""

    def __init__(self, sink: AuditSinkPort, record: TurnAuditRecord) -> None:
        self._sink = sink
        self._record = record

    async def run(self, connection: TransactionConnection) -> None:
        await connection.execute("INSERT INTO described_work (id) VALUES (1)")
        await self._sink.append(self._record)
        msg = "described work failed"
        raise RuntimeError(msg)


class AppendTurn(TransactionalWork):
    def __init__(self, sink: AuditSinkPort, record: TurnAuditRecord) -> None:
        self._sink = sink
        self._record = record

    async def run(self, connection: TransactionConnection) -> None:
        await self._sink.append(self._record)


class HeldAppend(TransactionalWork):
    """Append, then wait, so the session lock stays held until release."""

    def __init__(
        self,
        sink: AuditSinkPort,
        record: TurnAuditRecord,
        started: asyncio.Event,
        release: asyncio.Event,
    ) -> None:
        self._sink = sink
        self._record = record
        self._started = started
        self._release = release

    async def run(self, connection: TransactionConnection) -> None:
        await self._sink.append(self._record)
        self._started.set()
        await self._release.wait()


class EnlistedSink:
    """Append through the sink on the connection the unit of work commits."""

    def __init__(self, url: str, cipher: CipherPort, hasher: AuditRecordHash) -> None:
        self._url = url
        self._cipher = cipher
        self._hasher = hasher
        self._engine = DatabaseEngine(PostgresUrl(url).async_url())

    async def run(self, work: type[TransactionalWork], record: TurnAuditRecord) -> None:
        connection = await self._engine.connect()
        sink = PostgresAuditSink(connection, self._cipher, self._hasher)
        await SqlAlchemyUnitOfWork(connection).run(work(sink, record))

    async def dispose(self) -> None:
        await self._engine.dispose()


class TestAuditSinkTransaction:
    def _cipher(self) -> AesGcmEnvelope:
        return AesGcmEnvelope(key=bytes(range(32)), key_id=UUID(int=1))

    def _generated(self, hasher: AuditRecordHash) -> TurnAuditRecord:
        return SealedTurn(hasher).at(
            Samples()
            .audit_record()
            .model_copy(update={"retrieved_context_ids": (_CHUNK,)}),
            AuditRecordHash.GENESIS,
        )

    async def test_audit_record_and_described_work_commit_in_one_transaction(
        self, fresh_database: str
    ) -> None:
        Catalogue().install(fresh_database, with_probe=True)
        cipher = self._cipher()
        hasher = AuditRecordHash()
        record = self._generated(hasher)
        enlisted = EnlistedSink(fresh_database, cipher, hasher)
        try:
            await enlisted.run(DescribedTurn, record)
        finally:
            await enlisted.dispose()
        with (
            psycopg.connect(fresh_database) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute("SELECT count(*) FROM described_work")
            assert cursor.fetchone() == (1,)
            cursor.execute(
                """
                SELECT learner_prompt_redacted, model_revision, refused,
                       previous_record_hash, record_hash
                FROM turn_audit
                """
            )
            row = cursor.fetchone()
            assert row is not None
            prompt, revision, refused, previous, digest = row
            assert cipher.decrypt(bytes(prompt)) == (
                record.learner_prompt_redacted.encode()
            )
            assert revision == record.model_revision
            assert refused is False
            assert previous == AuditRecordHash.GENESIS
            assert digest == record.record_hash
            cursor.execute("SELECT chunk_id, ordinal FROM turn_citation")
            assert cursor.fetchone() == (UUID(_CHUNK), 0)

    async def test_rolled_back_turn_leaves_no_partial_audit_row(
        self, fresh_database: str
    ) -> None:
        Catalogue().install(fresh_database, with_probe=True)
        hasher = AuditRecordHash()
        enlisted = EnlistedSink(fresh_database, self._cipher(), hasher)
        try:
            with pytest.raises(RuntimeError, match="described work failed"):
                await enlisted.run(AbortedTurn, self._generated(hasher))
        finally:
            await enlisted.dispose()
        with (
            psycopg.connect(fresh_database) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute("SELECT count(*) FROM described_work")
            assert cursor.fetchone() == (0,)
            cursor.execute("SELECT count(*) FROM turn_audit")
            assert cursor.fetchone() == (0,)
            cursor.execute("SELECT count(*) FROM turn_citation")
            assert cursor.fetchone() == (0,)

    async def test_chain_holds_across_successive_turns_in_one_session(
        self, fresh_database: str
    ) -> None:
        Catalogue().install(fresh_database, with_probe=False)
        hasher = AuditRecordHash()
        sealer = SealedTurn(hasher)
        first = sealer.at(Samples().stopped_audit_record(), AuditRecordHash.GENESIS)
        second = sealer.at(
            Samples()
            .stopped_audit_record()
            .model_copy(update={"turn_id": _SECOND_TURN, "turn_index": 1}),
            first.record_hash,
        )
        enlisted = EnlistedSink(fresh_database, self._cipher(), hasher)
        try:
            await enlisted.run(AppendTurn, first)
            await enlisted.run(AppendTurn, second)
        finally:
            await enlisted.dispose()
        with (
            psycopg.connect(fresh_database) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                """
                SELECT turn_index, previous_record_hash, record_hash, model_revision
                FROM turn_audit
                ORDER BY turn_index
                """
            )
            rows = cursor.fetchall()
        assert rows == [
            (0, AuditRecordHash.GENESIS, first.record_hash, None),
            (1, first.record_hash, second.record_hash, None),
        ]
        assert ChainVerifier(hasher).find_break((first, second)) is None

    async def test_a_second_append_waits_until_the_session_lock_releases(
        self, fresh_database: str
    ) -> None:
        Catalogue().install(fresh_database, with_probe=False)
        cipher = self._cipher()
        hasher = AuditRecordHash()
        sealer = SealedTurn(hasher)
        first = sealer.at(Samples().stopped_audit_record(), AuditRecordHash.GENESIS)
        rival_record = sealer.at(
            Samples()
            .stopped_audit_record()
            .model_copy(
                update={"turn_id": _SECOND_TURN, "turn_index": 0},
            ),
            AuditRecordHash.GENESIS,
        )
        started = asyncio.Event()
        release = asyncio.Event()
        holder = asyncio.create_task(
            self._hold(fresh_database, cipher, hasher, first, started, release)
        )
        rival: asyncio.Task[None] | None = None
        try:
            await asyncio.wait_for(started.wait(), timeout=5)
            rival = asyncio.create_task(
                self._append(fresh_database, cipher, hasher, rival_record)
            )
            await asyncio.wait_for(
                self._session_lock_is_contended(fresh_database), timeout=5
            )
            release.set()
            await holder
            with pytest.raises(AuditAppendRejected, match="previous record hash"):
                await rival
        finally:
            release.set()
            if not holder.done():
                await holder
            if rival is not None and not rival.done():
                rival.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await rival
        with (
            psycopg.connect(fresh_database) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute("SELECT turn_id FROM turn_audit")
            assert cursor.fetchall() == [(first.turn_id,)]

    async def _hold(
        self,
        url: str,
        cipher: CipherPort,
        hasher: AuditRecordHash,
        record: TurnAuditRecord,
        started: asyncio.Event,
        release: asyncio.Event,
    ) -> None:
        engine = DatabaseEngine(PostgresUrl(url).async_url())
        connection = await engine.connect()
        sink = PostgresAuditSink(connection, cipher, hasher)
        try:
            await SqlAlchemyUnitOfWork(connection).run(
                HeldAppend(sink, record, started, release)
            )
        finally:
            await engine.dispose()

    async def _session_lock_is_contended(self, url: str) -> None:
        """Wait until one session holds the chain lock and another is queued."""
        while True:
            with (
                psycopg.connect(url) as connection,
                connection.cursor() as cursor,
            ):
                cursor.execute(
                    """
                    SELECT
                        count(*) FILTER (WHERE granted),
                        count(*) FILTER (WHERE NOT granted)
                    FROM pg_locks
                    WHERE locktype = 'advisory'
                    """
                )
                row = cursor.fetchone()
            assert row is not None
            granted, waiting = row
            if granted >= 1 and waiting >= 1:
                return
            await asyncio.sleep(0.05)

    async def _append(
        self,
        url: str,
        cipher: CipherPort,
        hasher: AuditRecordHash,
        record: TurnAuditRecord,
    ) -> None:
        enlisted = EnlistedSink(url, cipher, hasher)
        try:
            await enlisted.run(AppendTurn, record)
        finally:
            await enlisted.dispose()
