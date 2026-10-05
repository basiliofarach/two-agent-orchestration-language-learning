"""One request, one connection: retrieval and its audit row commit together.

Everything a turn touches is resolved from one container scope, the way
``Provide`` resolves it for a route (DEC-0013, DEC-0014). Curation is committed
beforehand on the operator path; a turn cannot ingest (DEC-0001).
"""

import base64
from datetime import UTC, datetime
from uuid import UUID

import psycopg
import pytest
from pydantic import SecretStr
from tests.support.curation import Curator
from tests.support.migrated_database import MigratedDatabase, PostgresUrl
from tests.support.samples import Samples
from tests.support.sealed_turn import SealedTurn
from tests.unit.test_container import FixedSettings

from tutor_api.adapters.persistence.database import DatabaseEngine
from tutor_api.container import ApplicationContainer
from tutor_api.di.container import Container, RequestScope
from tutor_api.settings import ApplicationSettings
from tutor_core.domain.audit.record_hash import AuditRecordHash
from tutor_core.domain.models.corpus import CorpusDocument
from tutor_core.domain.models.safety import StoredLearnerPrompt
from tutor_core.domain.ports.audit_sink import AuditSinkPort
from tutor_core.domain.ports.cipher import CipherPort
from tutor_core.domain.ports.knowledge_base import KnowledgeBasePort
from tutor_core.domain.ports.pii_redaction import PiiRedactionPort
from tutor_core.domain.ports.policy_artifact import PolicyArtifactPort
from tutor_core.domain.ports.unit_of_work import (
    TransactionalWork,
    TransactionConnection,
    UnitOfWorkPort,
)

_KEK = bytes(range(32))
_DOCUMENT = UUID("00000000-0000-4000-8000-000000000080")
_TEXT = "The library is open."


class Wired:
    """The production container over one test database."""

    def __init__(self, url: str) -> None:
        self._url = url

    def container(self) -> Container:
        settings = ApplicationSettings(
            _env_file=None,  # type: ignore[call-arg]
            application_database_url=PostgresUrl(self._url).async_url(),
            tutor_kek=SecretStr(base64.b64encode(_KEK).decode()),
            tutor_kek_id=UUID(int=1),
        )
        return ApplicationContainer(FixedSettings(settings)).build()

    async def install(self, container: Container) -> None:
        database = MigratedDatabase()
        database.upgrade(self._url)
        database.seed_learner(self._url)
        cipher = container.resolve(CipherPort)
        assert isinstance(cipher, CipherPort)
        curator = Curator(PostgresUrl(self._url).async_url(), cipher)
        await curator.publish(Samples().policy_card(), datetime(2026, 1, 1, tzinfo=UTC))
        await curator.ingest(
            CorpusDocument(
                document_id=_DOCUMENT,
                source_uri="kb://library",
                version="1",
                review_status="approved",
                content=_TEXT,
            )
        )


class Turn(TransactionalWork):
    """Redact, read the policy, retrieve, and append — on the scope's ports."""

    def __init__(self, scope: RequestScope, fail: bool) -> None:
        self._redactor = scope.resolve(PiiRedactionPort)
        self._policy = scope.resolve(PolicyArtifactPort)
        self._knowledge = scope.resolve(KnowledgeBasePort)
        self._sink = scope.resolve(AuditSinkPort)
        self._shared = scope.resolve(TransactionConnection)
        self._fail = fail
        self.cited: tuple[UUID, ...] = ()

    async def run(self, connection: TransactionConnection) -> None:
        # The unit of work hands over the scope's connection: the one the
        # policy, knowledge base and sink were built with.
        assert connection is self._shared
        assert isinstance(self._redactor, PiiRedactionPort)
        assert isinstance(self._policy, PolicyArtifactPort)
        assert isinstance(self._knowledge, KnowledgeBasePort)
        assert isinstance(self._sink, AuditSinkPort)
        redacted = self._redactor.redact(f"My name is Ada. {_TEXT}")
        version = await self._policy.version()
        result = await self._knowledge.retrieve(
            Samples().redacted_request(redacted.text)
        )
        self.cited = tuple(snippet.chunk_id for snippet in result.snippets)
        drafted = (
            Samples()
            .stopped_audit_record()
            .model_copy(
                update={
                    "learner_prompt": StoredLearnerPrompt.model_validate(redacted),
                    "retrieved_context_ids": tuple(str(item) for item in self.cited),
                    "policy_version": version,
                }
            )
        )
        hasher = AuditRecordHash()
        await self._sink.append(SealedTurn(hasher).at(drafted, AuditRecordHash.GENESIS))
        if self._fail:
            msg = "turn failed after the audit append"
            raise RuntimeError(msg)


class Counts:
    def __init__(self, url: str) -> None:
        self._url = url

    def of(self, table: str) -> int:
        with psycopg.connect(self._url) as connection:
            row = connection.execute(f"SELECT count(*) FROM {table}").fetchone()  # noqa: S608
        assert row is not None
        return int(row[0])


class TestRequestTransaction:
    async def _run(self, url: str, fail: bool) -> Turn:
        wired = Wired(url)
        container = wired.container()
        await wired.install(container)
        scope = container.scope()
        turn = Turn(scope, fail)
        unit_of_work = scope.resolve(UnitOfWorkPort)
        assert isinstance(unit_of_work, UnitOfWorkPort)
        try:
            await unit_of_work.run(turn)
        finally:
            engine = container.resolve(DatabaseEngine)
            assert isinstance(engine, DatabaseEngine)
            await engine.dispose()
        return turn

    async def test_retrieval_and_its_audit_row_commit_together(
        self, fresh_database: str
    ) -> None:
        turn = await self._run(fresh_database, fail=False)
        counts = Counts(fresh_database)
        assert counts.of("turn_audit") == 1
        assert counts.of("turn_citation") == len(turn.cited) == 1
        with psycopg.connect(fresh_database) as connection:
            cited = connection.execute("SELECT chunk_id FROM turn_citation").fetchone()
            version = connection.execute(
                "SELECT policy_version FROM turn_audit"
            ).fetchone()
        assert cited == (turn.cited[0],)
        assert version == ("policy-1",)

    async def test_a_failed_turn_leaves_no_audit_row_and_no_citation(
        self, fresh_database: str
    ) -> None:
        with pytest.raises(RuntimeError, match="turn failed"):
            await self._run(fresh_database, fail=True)
        counts = Counts(fresh_database)
        assert counts.of("turn_audit") == 0
        assert counts.of("turn_citation") == 0
        # Curation was committed before the turn and is not the turn's to undo.
        assert counts.of("kb_document") == 1

    async def test_the_stored_prompt_is_the_redacted_one(
        self, fresh_database: str
    ) -> None:
        await self._run(fresh_database, fail=False)
        container = Wired(fresh_database).container()
        cipher = container.resolve(CipherPort)
        assert isinstance(cipher, CipherPort)
        with psycopg.connect(fresh_database) as connection:
            row = connection.execute(
                "SELECT learner_prompt_redacted FROM turn_audit"
            ).fetchone()
        assert row is not None
        stored = cipher.decrypt(bytes(row[0])).decode("utf-8")
        assert "Ada" not in stored
        assert "[REDACTED:person_name]" in stored
