"""Seed a fresh database so the request path has something to serve.

Run as the migration owner, never as the application role: the request path
has no grant to publish a policy, ingest a document or enrol a learner, and
that absence is the DEC-0001 capability claim. Every step is idempotent, so
running the seed twice changes nothing the second time.

    uv run python -m tutor_api.curation.prototype_seed
"""

import asyncio
import sys
from collections.abc import Mapping
from datetime import timedelta
from typing import cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from tutor_api.adapters.llm.local_embedding import LocalEmbedding
from tutor_api.adapters.persistence.database import DatabaseEngine
from tutor_api.adapters.persistence.database_url import (
    DriverSwap,
    MigrationDatabaseUrl,
)
from tutor_api.adapters.persistence.knowledge_base import (
    ChunkIdentifiers,
    PassageSplitter,
    PostgresCorpusIngestion,
    VectorLiteral,
)
from tutor_api.adapters.persistence.learner_history import HistoryOutcomeCodec
from tutor_api.adapters.persistence.schema import BaseSchema
from tutor_api.adapters.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tutor_api.adapters.persistence.versioned_policy import (
    PolicyCardCodec,
    PolicyVersionWriter,
)
from tutor_api.container import ApplicationContainer, SettingsProvider
from tutor_api.di.container import Container
from tutor_api.prototype import PrototypeCopy, PrototypePolicyCard
from tutor_api.settings import ApplicationSettings
from tutor_core.domain.models.corpus import CorpusDocument
from tutor_core.domain.policy.lineage import PolicyRuleLineage
from tutor_core.domain.ports.cipher import CipherPort
from tutor_core.domain.ports.clock import ClockPort
from tutor_core.domain.ports.unit_of_work import (
    TransactionalWork,
    TransactionConnection,
)


class SeedPlan(BaseModel):
    """What the seed writes. Fixed identifiers, so a re-run finds them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_version: str
    conflict_threshold: str
    document_id: UUID
    document_uri: str
    document_content: str
    learner_id: UUID
    proficiency_level: str
    session_id: UUID
    tutor_id: str
    history: tuple[tuple[UUID, str, bool], ...]


class PrototypePlan:
    """The demo data: one card, one Spanish-greetings document, one learner."""

    def plan(self, threshold: float) -> SeedPlan:
        """Return the plan. ``threshold`` must equal the gate's setting."""
        return SeedPlan(
            policy_version="prototype-1",
            conflict_threshold=str(threshold),
            document_id=UUID("10000000-0000-4000-8000-000000000001"),
            document_uri="kb://spanish/greetings",
            document_content="\n\n".join(
                (
                    "Hola means hello in Spanish.",
                    "Buenos dias means good morning in Spanish.",
                    "Buenas noches means good night in Spanish.",
                    "Adios means goodbye in Spanish.",
                    "Gracias means thank you in Spanish.",
                )
            ),
            learner_id=UUID("20000000-0000-4000-8000-000000000001"),
            proficiency_level="A1",
            session_id=UUID("30000000-0000-4000-8000-000000000001"),
            tutor_id="tutor-demo",
            history=(
                (UUID("40000000-0000-4000-8000-000000000001"), "greet-1", True),
                (UUID("40000000-0000-4000-8000-000000000002"), "greet-2", False),
            ),
        )


class PublishedVersion(TransactionalWork):
    """Read whether a policy version is already published."""

    def __init__(self, version: str, found: list[bool]) -> None:
        self._version = version
        self._found = found

    async def run(self, connection: TransactionConnection) -> None:
        """Record whether the version row exists."""
        row = await connection.fetch_one(
            "SELECT 1 FROM policy_version WHERE version = :version",
            {"version": self._version},
        )
        self._found.append(row is not None)


class PublishPolicy(TransactionalWork):
    """Publish the prototype card. Its own transaction: it runs SERIALIZABLE."""

    def __init__(self, plan: SeedPlan, cipher: CipherPort, clock: ClockPort) -> None:
        self._plan = plan
        self._cipher = cipher
        self._clock = clock

    async def run(self, connection: TransactionConnection) -> None:
        """Publish, effective now."""
        card = PrototypePolicyCard(PrototypeCopy()).build(
            self._plan.policy_version, self._plan.conflict_threshold
        )
        writer = PolicyVersionWriter(
            connection, PolicyCardCodec(self._cipher), PolicyRuleLineage()
        )
        await writer.publish(card, self._clock.now())


class IngestAndEnrol(TransactionalWork):
    """Ingest the document and enrol the learner, each only if absent."""

    def __init__(self, plan: SeedPlan, cipher: CipherPort, clock: ClockPort) -> None:
        self._plan = plan
        self._cipher = cipher
        self._clock = clock

    async def run(self, connection: TransactionConnection) -> None:
        """Write whatever the plan names that is not there yet."""
        await self._ingest(connection)
        await self._enrol(connection)

    async def _ingest(self, connection: TransactionConnection) -> None:
        plan = self._plan
        row = await connection.fetch_one(
            "SELECT 1 FROM kb_document WHERE id = :id", {"id": plan.document_id}
        )
        if row is not None:
            return
        ingestion = PostgresCorpusIngestion(
            connection,
            LocalEmbedding(BaseSchema().embedding_dimensions()),
            self._cipher,
            ChunkIdentifiers(),
            PassageSplitter(),
            VectorLiteral(),
        )
        await ingestion.ingest(
            CorpusDocument(
                document_id=plan.document_id,
                source_uri=plan.document_uri,
                version="1",
                review_status="approved",
                content=plan.document_content,
            )
        )

    async def _enrol(self, connection: TransactionConnection) -> None:
        plan = self._plan
        now = self._clock.now()
        await connection.execute(
            """
            INSERT INTO learner (learner_id, pseudonym, proficiency_level, retain_until)
            VALUES (:learner_id, :pseudonym, :proficiency, :retain_until)
            ON CONFLICT (learner_id) DO NOTHING
            """,
            {
                "learner_id": plan.learner_id,
                "pseudonym": self._seal("demo-learner"),
                "proficiency": self._seal(plan.proficiency_level),
                "retain_until": now + timedelta(days=365),
            },
        )
        for event_id, item_id, correct in plan.history:
            await connection.execute(
                """
                INSERT INTO learner_history_event (
                    id, learner_id, item_id, correct, occurred_at
                ) VALUES (:id, :learner_id, :item_id, :correct, :occurred_at)
                ON CONFLICT (id) DO NOTHING
                """,
                {
                    "id": event_id,
                    "learner_id": plan.learner_id,
                    "item_id": self._seal(item_id),
                    "correct": self._cipher.encrypt(
                        HistoryOutcomeCodec().encode(correct)
                    ),
                    "occurred_at": now,
                },
            )
        await connection.execute(
            """
            INSERT INTO tutoring_session (id, tutor_id, learner_id, started_at)
            VALUES (:id, :tutor_id, :learner_id, :started_at)
            ON CONFLICT (id) DO NOTHING
            """,
            {
                "id": plan.session_id,
                "tutor_id": self._seal(plan.tutor_id),
                "learner_id": plan.learner_id,
                "started_at": now,
            },
        )

    def _seal(self, text: str) -> bytes:
        return self._cipher.encrypt(text.encode("utf-8"))


class PrototypeSeed:
    """Run the three steps, each in its own unit of work, on the owner URL."""

    def __init__(self, engine: DatabaseEngine, container: Container) -> None:
        self._engine = engine
        self._container = container

    async def run(self, plan: SeedPlan) -> SeedPlan:
        """Seed, then return the plan so the caller can print its identifiers."""
        cipher = cast(CipherPort, self._container.resolve(CipherPort))
        clock = cast(ClockPort, self._container.resolve(ClockPort))
        found: list[bool] = []
        await self._unit(PublishedVersion(plan.policy_version, found))
        if not found[0]:
            await self._unit(PublishPolicy(plan, cipher, clock))
        await self._unit(IngestAndEnrol(plan, cipher, clock))
        return plan

    async def _unit(self, work: TransactionalWork) -> None:
        await SqlAlchemyUnitOfWork(await self._engine.connect()).run(work)


class SeedMain:
    """Compose the seed from the environment, as Alembic does, and run it."""

    async def run(self, settings: ApplicationSettings) -> int:
        """Seed and print the identifiers a turn needs. Returns an exit code."""
        threshold = settings.conflict_confidence_threshold
        if threshold is None:
            msg = "CONFLICT_CONFIDENCE_THRESHOLD is not set. Export it."
            raise ValueError(msg)
        container = ApplicationContainer(FixedSettingsProvider(settings)).build()
        owner = DriverSwap("postgresql+asyncpg").apply(
            MigrationDatabaseUrl(settings).value()
        )
        engine = DatabaseEngine(owner)
        try:
            plan = await PrototypeSeed(engine, container).run(
                PrototypePlan().plan(threshold)
            )
        finally:
            await engine.dispose()
        sys.stdout.write(
            f"policy_version={plan.policy_version}\n"
            f"learner_id={plan.learner_id}\n"
            f"session_id={plan.session_id}\n"
        )
        return 0


class FixedSettingsProvider(SettingsProvider):
    """The settings the seed already read, so the container reads them once."""

    def __init__(self, settings: ApplicationSettings) -> None:
        self._settings = settings

    def create(self, resolved: Mapping[type, object]) -> object:
        return self._settings


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(asyncio.run(SeedMain().run(ApplicationSettings())))
