"""Two policy versions coexist. A turn keeps the one in force when it started."""

import json
from datetime import UTC, datetime
from uuid import UUID

import psycopg
import pytest
from tests.support.curation import Curator
from tests.support.migrated_database import MigratedDatabase, PostgresUrl
from tests.support.samples import Samples
from tests.support.sealed_turn import SealedTurn

from tutor_api.adapters.frozen_clock import FrozenClock
from tutor_api.adapters.persistence.aes_gcm_envelope import AesGcmEnvelope
from tutor_api.adapters.persistence.audit_sink import PostgresAuditSink
from tutor_api.adapters.persistence.database import DatabaseEngine
from tutor_api.adapters.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tutor_api.adapters.persistence.versioned_policy import (
    PolicyCardCodec,
    PolicyVersionMissing,
    VersionedPolicyCard,
)
from tutor_core.domain.audit.record_hash import AuditRecordHash
from tutor_core.domain.policy.policy_card import ArticleMapping, PolicyCard
from tutor_core.domain.ports.cipher import CipherPort
from tutor_core.domain.ports.unit_of_work import (
    TransactionalWork,
    TransactionConnection,
)

_MARCH = datetime(2026, 3, 1, tzinfo=UTC)
_JULY = datetime(2026, 7, 1, tzinfo=UTC)
_BEFORE = datetime(2025, 1, 1, tzinfo=UTC)


class SecondVersion:
    """policy-2 adds a rule. Existing ids keep their statements."""

    def card(self) -> PolicyCard:
        current = Samples().policy_card()
        added = Samples().policy_rule("log-version", "record policy_version", "12")
        return current.model_copy(
            update={
                "version": "policy-2",
                "allowed_actions": current.allowed_actions + (added,),
            }
        )


class StartTurn(TransactionalWork):
    """Read the version in force at ``at``; optionally append the turn row."""

    def __init__(self, cipher: CipherPort, at: datetime, record: bool) -> None:
        self._cipher = cipher
        self._at = at
        self._record = record
        self.version: str | None = None

    async def run(self, connection: TransactionConnection) -> None:
        policy = VersionedPolicyCard(
            connection, FrozenClock(self._at), PolicyCardCodec(self._cipher)
        )
        self.version = await policy.version()
        if not self._record:
            return
        hasher = AuditRecordHash()
        sink = PostgresAuditSink(connection, self._cipher, hasher)
        record = SealedTurn(hasher).at(
            Samples()
            .stopped_audit_record()
            .model_copy(update={"policy_version": self.version}),
            AuditRecordHash.GENESIS,
        )
        await sink.append(record)


class PublishedPolicy:
    """Learner, session, and both policy versions, committed."""

    def __init__(self, url: str) -> None:
        self._url = url
        self.cipher = AesGcmEnvelope(key=bytes(range(32)), key_id=UUID(int=1))

    async def install(self) -> None:
        database = MigratedDatabase()
        database.upgrade(self._url)
        database.seed_learner(self._url)
        curator = Curator(PostgresUrl(self._url).async_url(), self.cipher)
        await curator.publish(Samples().policy_card(), datetime(2026, 1, 1, tzinfo=UTC))
        await curator.publish(SecondVersion().card(), datetime(2026, 6, 1, tzinfo=UTC))

    async def start(self, at: datetime, record: bool = False) -> str | None:
        work = StartTurn(self.cipher, at, record)
        engine = DatabaseEngine(PostgresUrl(self._url).async_url())
        try:
            await SqlAlchemyUnitOfWork(await engine.connect()).run(work)
        finally:
            await engine.dispose()
        return work.version


class TestVersionedPolicy:
    async def test_current_resolves_by_effective_from_and_both_rows_remain(
        self, fresh_database: str
    ) -> None:
        published = PublishedPolicy(fresh_database)
        await published.install()
        assert await published.start(_MARCH) == "policy-1"
        assert await published.start(_JULY) == "policy-2"
        with psycopg.connect(fresh_database) as connection:
            assert connection.execute(
                "SELECT count(*) FROM policy_version"
            ).fetchone() == (2,)

    async def test_a_version_that_is_not_yet_in_force_raises(
        self, fresh_database: str
    ) -> None:
        published = PublishedPolicy(fresh_database)
        await published.install()
        with pytest.raises(PolicyVersionMissing, match="no policy version"):
            await published.start(_BEFORE)

    async def test_the_audit_record_keeps_the_version_in_force_at_turn_start(
        self, fresh_database: str
    ) -> None:
        published = PublishedPolicy(fresh_database)
        await published.install()
        started = await published.start(_MARCH, record=True)
        later = await published.start(_JULY)
        with psycopg.connect(fresh_database) as connection:
            stored = connection.execute(
                "SELECT policy_version FROM turn_audit"
            ).fetchone()
        assert started == "policy-1"
        assert stored == ("policy-1",)
        assert later == "policy-2"


class LegacyPolicyRow:
    """One ``policy_version`` row in the pre-object action shape."""

    def __init__(self, cipher: CipherPort) -> None:
        self._cipher = cipher

    def insert(self, url: str) -> None:
        """Store string arrays, the shape published before ``PolicyRule``."""
        allowed = self._seal(["retrieve_vetted"])
        denied = self._seal(["open_web"])
        escalation = self._seal(["pause_routes_to_tutor"])
        mapping = ArticleMapping(article="12", locus="per-turn audit log")
        mappings = self._seal([mapping.model_dump(mode="json")])
        with psycopg.connect(url) as connection:
            connection.execute(
                """
                INSERT INTO policy_version (
                    version, allowed_actions, denied_actions, escalation_rules,
                    article_mappings, effective_from
                ) VALUES ('policy-legacy', %s, %s, %s, %s, '2026-01-01T00:00:00Z')
                """,
                (allowed, denied, escalation, mappings),
            )

    def _seal(self, payload: object) -> bytes:
        encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        return self._cipher.encrypt(encoded.encode("utf-8"))


class TestLegacyPolicyPayload:
    async def test_current_reads_a_string_array_published_earlier(
        self, fresh_database: str
    ) -> None:
        MigratedDatabase().upgrade(fresh_database)
        cipher = AesGcmEnvelope(key=bytes(range(32)), key_id=UUID(int=1))
        LegacyPolicyRow(cipher).insert(fresh_database)
        engine = DatabaseEngine(PostgresUrl(fresh_database).async_url())
        connection = await engine.connect()
        try:
            card = await VersionedPolicyCard(
                connection, FrozenClock(_MARCH), PolicyCardCodec(cipher)
            ).current()
        finally:
            await connection.close()
            await engine.dispose()
        assert card.version == "policy-legacy"
        assert card.allowed_actions[0].policy_rule_id == "retrieve_vetted"
        assert card.allowed_actions[0].article is None
        assert card.denied_actions[0].statement == "open_web"
        assert card.article_mappings[0].locus == "per-turn audit log"
