"""The operator path: publish a policy version, ingest a document, commit.

Curation is not a request capability (DEC-0001), so the container has no
provider for it. Tests do it here, each step in a unit of work of its own,
before any turn runs.
"""

from datetime import datetime

from tutor_api.adapters.llm.local_embedding import LocalEmbedding
from tutor_api.adapters.persistence.database import DatabaseEngine
from tutor_api.adapters.persistence.knowledge_base import (
    ChunkIdentifiers,
    CitedSources,
    CosineConfidence,
    PassageSplitter,
    PgVectorKnowledgeBase,
    PostgresCorpusIngestion,
    VectorLiteral,
)
from tutor_api.adapters.persistence.schema import BaseSchema
from tutor_api.adapters.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tutor_api.adapters.persistence.versioned_policy import (
    PolicyCardCodec,
    PolicyVersionWriter,
)
from tutor_core.domain.models.corpus import CorpusDocument
from tutor_core.domain.models.retrieval import (
    RedactedRetrievalRequest,
    RetrievalResult,
)
from tutor_core.domain.policy.lineage import PolicyRuleLineage
from tutor_core.domain.policy.policy_card import PolicyCard
from tutor_core.domain.ports.cipher import CipherPort
from tutor_core.domain.ports.unit_of_work import (
    TransactionalWork,
    TransactionConnection,
)


class PublishWork(TransactionalWork):
    def __init__(
        self, cipher: CipherPort, card: PolicyCard, effective_from: datetime
    ) -> None:
        self._cipher = cipher
        self._card = card
        self._effective_from = effective_from

    async def run(self, connection: TransactionConnection) -> None:
        writer = PolicyVersionWriter(
            connection, PolicyCardCodec(self._cipher), PolicyRuleLineage()
        )
        await writer.publish(self._card, self._effective_from)


class IngestWork(TransactionalWork):
    def __init__(self, cipher: CipherPort, document: CorpusDocument) -> None:
        self._cipher = cipher
        self._document = document

    async def run(self, connection: TransactionConnection) -> None:
        ingestion = PostgresCorpusIngestion(
            connection,
            LocalEmbedding(BaseSchema().embedding_dimensions()),
            self._cipher,
            ChunkIdentifiers(),
            PassageSplitter(),
            VectorLiteral(),
        )
        await ingestion.ingest(self._document)


class RetrieveWork(TransactionalWork):
    def __init__(self, cipher: CipherPort, request: RedactedRetrievalRequest) -> None:
        self._cipher = cipher
        self._request = request
        self.result: RetrievalResult | None = None

    async def run(self, connection: TransactionConnection) -> None:
        knowledge = PgVectorKnowledgeBase(
            connection,
            LocalEmbedding(BaseSchema().embedding_dimensions()),
            self._cipher,
            VectorLiteral(),
            CosineConfidence(),
            CitedSources(),
        )
        self.result = await knowledge.retrieve(self._request)


class Curator:
    """Commit curation steps against one database, as the owner role."""

    def __init__(self, async_url: str, cipher: CipherPort) -> None:
        self._url = async_url
        self._cipher = cipher

    async def publish(self, card: PolicyCard, effective_from: datetime) -> None:
        await self._commit(PublishWork(self._cipher, card, effective_from))

    async def ingest(self, document: CorpusDocument) -> None:
        await self._commit(IngestWork(self._cipher, document))

    async def retrieve(self, request: RedactedRetrievalRequest) -> RetrievalResult:
        work = RetrieveWork(self._cipher, request)
        await self._commit(work)
        assert work.result is not None
        return work.result

    async def _commit(self, work: TransactionalWork) -> None:
        engine = DatabaseEngine(self._url)
        try:
            await SqlAlchemyUnitOfWork(await engine.connect()).run(work)
        finally:
            await engine.dispose()
