"""Curated ingestion and pgvector retrieval (REQ-KB)."""

from uuid import UUID, uuid4

from tutor_api.adapters.persistence.base import BaseRepository
from tutor_core.domain.models.corpus import CorpusDocument, IngestedDocument
from tutor_core.domain.models.retrieval import (
    RedactedRetrievalRequest,
    RetrievalResult,
    Snippet,
    SourceRef,
)
from tutor_core.domain.ports.cipher import CipherPort
from tutor_core.domain.ports.corpus_ingestion import CorpusIngestionPort
from tutor_core.domain.ports.embedding import EmbeddingPort
from tutor_core.domain.ports.knowledge_base import KnowledgeBasePort
from tutor_core.domain.ports.unit_of_work import TransactionConnection


class PassageSplitter:
    """Split a document on blank lines. One block is one chunk."""

    def split(self, content: str) -> tuple[str, ...]:
        """Return the non-empty passages, in order."""
        parts = tuple(part.strip() for part in content.split("\n\n") if part.strip())
        if not parts:
            msg = "document has no passages"
            raise ValueError(msg)
        return parts


class VectorLiteral:
    """The text form pgvector accepts for a bound ``vector`` cast."""

    def render(self, values: tuple[float, ...]) -> str:
        """Render ``values`` as ``[0.10000000, ...]``."""
        return "[" + ",".join(format(value, ".8f") for value in values) + "]"


class CosineConfidence:
    """The score ``RetrievalResult.confidence`` carries.

    It is the greatest cosine similarity among the snippets returned,
    clamped to ``[0, 1]``. An empty result scores ``0``. The conflict gate
    (BE-14) thresholds against this number; it is not a probability.
    """

    def score(self, similarities: tuple[float, ...]) -> float:
        """Clamp the best similarity. No snippets score zero."""
        if not similarities:
            return 0.0
        best = max(similarities)
        if best < 0.0:
            return 0.0
        if best > 1.0:
            return 1.0
        return best


class CitedSources:
    """One ``SourceRef`` per document, in the order snippets appear."""

    def from_snippets(self, snippets: tuple[Snippet, ...]) -> tuple[SourceRef, ...]:
        """Drop a repeated source without dropping its snippets."""
        ordered: list[SourceRef] = []
        for snippet in snippets:
            if snippet.source not in ordered:
                ordered.append(snippet.source)
        return tuple(ordered)


class ChunkIdentifiers:
    """Fresh chunk ids. A new version of a source gets new ids."""

    def next(self) -> UUID:
        """One new chunk id."""
        return uuid4()


class PgVectorKnowledgeBase(BaseRepository, KnowledgeBasePort):
    """Retrieve approved chunks only. The filter is in the SQL (REQ-KB).

    Unreviewed documents are excluded by ``review_status``, not by a pass
    over the rows in Python, and the status is a literal in the statement
    rather than a constructor argument: wiring cannot widen it. Reads run on
    the request's enlisted connection (DEC-0014). ``confidence`` is the best
    cosine similarity of the rows returned; see ``CosineConfidence``.
    """

    _RETRIEVE = """
        SELECT c.id, c.ordinal, c.content,
               d.id, d.source_uri, d.version, d.review_status,
               1 - (c.embedding <=> CAST(CAST(:embedding AS text) AS vector))
                   AS similarity
        FROM kb_chunk AS c
        JOIN kb_document AS d ON d.id = c.document_id
        WHERE d.review_status = 'approved'
        ORDER BY c.embedding <=> CAST(CAST(:embedding AS text) AS vector)
        LIMIT :limit
        """

    def __init__(  # noqa: PLR0913 — each collaborator is injected (rule 3)
        self,
        connection: TransactionConnection,
        embedding: EmbeddingPort,
        cipher: CipherPort,
        vectors: VectorLiteral,
        confidence: CosineConfidence,
        sources: CitedSources,
    ) -> None:
        super().__init__(connection)
        self._embedding = embedding
        self._cipher = cipher
        self._vectors = vectors
        self._confidence = confidence
        self._sources = sources

    async def retrieve(self, request: RedactedRetrievalRequest) -> RetrievalResult:
        """Return sourced snippets, or an empty result when nothing matches."""
        literal = self._vectors.render(self._embedding.embed(request.prompt.text))
        rows = await self._fetch_all(
            self._RETRIEVE,
            {"embedding": literal, "limit": request.limit},
        )
        snippets, similarities = self._read(rows)
        return RetrievalResult(
            snippets=snippets,
            sources=self._sources.from_snippets(snippets),
            confidence=self._confidence.score(similarities),
        )

    def _read(
        self,
        rows: tuple[tuple[object, ...], ...],
    ) -> tuple[tuple[Snippet, ...], tuple[float, ...]]:
        snippets: list[Snippet] = []
        similarities: list[float] = []
        for row in rows:
            snippet, similarity = self._snippet(row)
            snippets.append(snippet)
            similarities.append(similarity)
        return tuple(snippets), tuple(similarities)

    def _snippet(self, row: tuple[object, ...]) -> tuple[Snippet, float]:
        source = SourceRef(
            document_id=self._uuid(row[3]),
            source_uri=str(row[4]),
            version=str(row[5]),
            review_status=str(row[6]),
        )
        snippet = Snippet(
            chunk_id=self._uuid(row[0]),
            content=self._cipher.decrypt(self._ciphertext(row[2])).decode("utf-8"),
            source=source,
            ordinal=int(str(row[1])),
        )
        return snippet, float(str(row[7]))


class PostgresCorpusIngestion(BaseRepository, CorpusIngestionPort):
    """Insert a document and its chunks. There is no update statement.

    Chunk text is ciphertext. The embedding stays a vector so nearest
    neighbour search still works (DEC-0012). ``review_status`` is the
    document's own status; this class does not fill one in.
    """

    _DOCUMENT = """
        INSERT INTO kb_document (id, source_uri, version, review_status)
        VALUES (:id, :source_uri, :version, :review_status)
        """

    _CHUNK = """
        INSERT INTO kb_chunk (id, document_id, ordinal, content, embedding)
        VALUES (
            :id, :document_id, :ordinal, :content,
            CAST(CAST(:embedding AS text) AS vector)
        )
        """

    def __init__(  # noqa: PLR0913 — each collaborator is injected (rule 3)
        self,
        connection: TransactionConnection,
        embedding: EmbeddingPort,
        cipher: CipherPort,
        identifiers: ChunkIdentifiers,
        passages: PassageSplitter,
        vectors: VectorLiteral,
    ) -> None:
        super().__init__(connection)
        self._embedding = embedding
        self._cipher = cipher
        self._identifiers = identifiers
        self._passages = passages
        self._vectors = vectors

    async def ingest(self, document: CorpusDocument) -> IngestedDocument:
        """Insert a new document row and one chunk row per passage."""
        passages = self._passages.split(document.content)
        await self._execute(
            self._DOCUMENT,
            {
                "id": document.document_id,
                "source_uri": document.source_uri,
                "version": document.version,
                "review_status": document.review_status,
            },
        )
        chunk_ids = [
            await self._insert_chunk(document, ordinal, passage)
            for ordinal, passage in enumerate(passages)
        ]
        return IngestedDocument(
            document_id=document.document_id, chunk_ids=tuple(chunk_ids)
        )

    async def _insert_chunk(
        self, document: CorpusDocument, ordinal: int, passage: str
    ) -> UUID:
        chunk_id = self._identifiers.next()
        await self._execute(
            self._CHUNK,
            {
                "id": chunk_id,
                "document_id": document.document_id,
                "ordinal": ordinal,
                "content": self._cipher.encrypt(passage.encode("utf-8")),
                "embedding": self._vectors.render(self._embedding.embed(passage)),
            },
        )
        return chunk_id
