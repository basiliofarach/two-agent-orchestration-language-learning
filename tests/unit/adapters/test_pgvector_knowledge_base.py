"""Retrieval filters in SQL. Ingestion inserts and does not update."""

import inspect
from uuid import UUID

import pytest
from tests.contract.test_port_contracts import (
    CorpusIngestionPortContract,
    KnowledgeBasePortContract,
)
from tests.support.reversible_cipher import ReversibleCipher
from tests.support.samples import Samples
from tests.support.scripted_connection import ScriptedConnection

from tutor_api.adapters.llm.local_embedding import LocalEmbedding
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
from tutor_core.domain.ports.corpus_ingestion import CorpusIngestionPort
from tutor_core.domain.ports.knowledge_base import KnowledgeBasePort

_DOCUMENT = UUID("00000000-0000-4000-8000-000000000060")
_CHUNK = UUID("00000000-0000-4000-8000-000000000061")
_SECOND = UUID("00000000-0000-4000-8000-000000000062")


class FixedChunks(ChunkIdentifiers):
    """Hand out a fixed sequence so a unit test can see the bound ids."""

    def __init__(self, identifiers: tuple[UUID, ...]) -> None:
        self._identifiers = list(identifiers)

    def next(self) -> UUID:
        return self._identifiers.pop(0)


class Wired:
    """The adapters with every collaborator handed in, as the container does."""

    def embedding(self) -> LocalEmbedding:
        return LocalEmbedding(BaseSchema().embedding_dimensions())

    def knowledge(self, connection: ScriptedConnection) -> PgVectorKnowledgeBase:
        return PgVectorKnowledgeBase(
            connection,
            self.embedding(),
            ReversibleCipher(),
            VectorLiteral(),
            CosineConfidence(),
            CitedSources(),
        )

    def ingestion(
        self, connection: ScriptedConnection, chunks: tuple[UUID, ...]
    ) -> PostgresCorpusIngestion:
        return PostgresCorpusIngestion(
            connection,
            self.embedding(),
            ReversibleCipher(),
            FixedChunks(chunks),
            PassageSplitter(),
            VectorLiteral(),
        )


class ChunkRow:
    """One retrieval row. Content is sealed so the knowledge base can open it."""

    def __init__(
        self, content: str, similarity: float, chunk_id: UUID = _CHUNK
    ) -> None:
        self._content = content
        self._similarity = similarity
        self._chunk_id: UUID | str = chunk_id

    def as_text_id(self) -> "ChunkRow":
        self._chunk_id = str(_CHUNK)
        return self

    def as_memoryview(self) -> tuple[object, ...]:
        row = self._row()
        sealed = ReversibleCipher().encrypt(self._content.encode("utf-8"))
        return (row[0], row[1], memoryview(sealed), *row[3:])

    def _row(self) -> tuple[object, ...]:
        return (
            self._chunk_id,
            0,
            ReversibleCipher().encrypt(self._content.encode("utf-8")),
            _DOCUMENT,
            "kb://library",
            "1",
            "approved",
            self._similarity,
        )


class TestPgVectorKnowledgeBaseContract(KnowledgeBasePortContract):
    def port(self) -> KnowledgeBasePort:
        return Wired().knowledge(ScriptedConnection())


class TestPostgresCorpusIngestionContract(CorpusIngestionPortContract):
    def port(self) -> CorpusIngestionPort:
        return Wired().ingestion(ScriptedConnection(), (_CHUNK,))


class TestPgVectorKnowledgeBase:
    async def test_the_review_filter_is_a_literal_in_the_sql(self) -> None:
        connection = ScriptedConnection()
        result = (
            await Wired().knowledge(connection).retrieve(Samples().redacted_request())
        )
        assert result.snippets == ()
        assert result.sources == ()
        assert result.confidence == 0.0
        assert "d.review_status = 'approved'" in connection.statements[0]
        assert "review_status" not in connection.parameters[0]
        assert "UPDATE" not in connection.statements[0].upper()

    def test_wiring_cannot_widen_the_review_filter(self) -> None:
        """No constructor argument names a review status (REQ-KB)."""
        names = inspect.signature(PgVectorKnowledgeBase).parameters
        assert not any("review" in name for name in names)

    async def test_the_redacted_prompt_is_what_is_embedded(self) -> None:
        connection = ScriptedConnection()
        request = Samples().redacted_request("Email [REDACTED:email]", limit=3)
        await Wired().knowledge(connection).retrieve(request)
        expected = VectorLiteral().render(
            Wired().embedding().embed(request.prompt.text)
        )
        assert connection.parameters[0]["embedding"] == expected
        assert connection.parameters[0]["limit"] == 3

    async def test_a_snippet_carries_source_metadata_and_confidence(self) -> None:
        connection = ScriptedConnection(
            (ChunkRow("The library is open.", 0.75)._row(),)
        )
        result = (
            await Wired()
            .knowledge(connection)
            .retrieve(Samples().redacted_request("library"))
        )
        snippet = result.snippets[0]
        assert snippet.content == "The library is open."
        assert snippet.source.document_id == _DOCUMENT
        assert snippet.source.source_uri == "kb://library"
        assert snippet.source.version == "1"
        assert snippet.source.review_status == "approved"
        assert result.confidence == pytest.approx(0.75)
        assert result.sources == (snippet.source,)

    async def test_a_string_chunk_id_and_a_memoryview_are_accepted(self) -> None:
        row = ChunkRow("The library is open.", 0.5).as_text_id().as_memoryview()
        result = (
            await Wired()
            .knowledge(ScriptedConnection((row,)))
            .retrieve(Samples().redacted_request("library"))
        )
        assert result.snippets[0].chunk_id == _CHUNK

    async def test_two_chunks_of_one_document_cite_it_once(self) -> None:
        first = ChunkRow("The library is open.", 0.9, _CHUNK)._row()
        second = ChunkRow("Bring a notebook.", 0.4, _SECOND)._row()
        result = (
            await Wired()
            .knowledge(ScriptedConnection((first, second)))
            .retrieve(Samples().redacted_request("library"))
        )
        assert len(result.snippets) == 2
        assert len(result.sources) == 1

    async def test_confidence_clamps_to_the_unit_interval(self) -> None:
        high = ScriptedConnection((ChunkRow("a", 1.5)._row(),))
        low = ScriptedConnection((ChunkRow("a", -0.2)._row(),))
        request = Samples().redacted_request("library")
        assert (await Wired().knowledge(high).retrieve(request)).confidence == 1.0
        assert (await Wired().knowledge(low).retrieve(request)).confidence == 0.0

    async def test_content_that_is_not_ciphertext_is_rejected(self) -> None:
        row = ChunkRow("a", 0.2)._row()
        broken = (row[0], row[1], "clear", *row[3:])
        with pytest.raises(ValueError, match="ciphertext column is not bytes"):
            await (
                Wired()
                .knowledge(ScriptedConnection((broken,)))
                .retrieve(Samples().redacted_request("library"))
            )

    def test_public_methods_are_retrieve_only(self) -> None:
        public = [
            name
            for name in dir(PgVectorKnowledgeBase)
            if not name.startswith("_")
            and callable(getattr(PgVectorKnowledgeBase, name))
        ]
        assert public == ["retrieve"]


class TestCosineConfidence:
    def test_no_snippets_score_zero(self) -> None:
        assert CosineConfidence().score(()) == 0.0

    def test_the_best_similarity_is_kept_inside_the_unit_interval(self) -> None:
        assert CosineConfidence().score((0.2, 0.8)) == pytest.approx(0.8)
        assert CosineConfidence().score((-0.4,)) == 0.0
        assert CosineConfidence().score((1.4,)) == 1.0


class TestPassageSplitter:
    def test_blank_lines_separate_passages(self) -> None:
        assert PassageSplitter().split("The library is open.\n\nBring a notebook.") == (
            "The library is open.",
            "Bring a notebook.",
        )

    def test_one_block_is_one_passage(self) -> None:
        assert PassageSplitter().split("The library is open.") == (
            "The library is open.",
        )

    def test_whitespace_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="no passages"):
            PassageSplitter().split("\n\n")


class TestVectorLiteral:
    def test_values_are_rendered_for_a_cast(self) -> None:
        assert VectorLiteral().render((0.5, 1.0)) == "[0.50000000,1.00000000]"


class TestChunkIdentifiers:
    def test_each_call_is_a_new_id(self) -> None:
        identifiers = ChunkIdentifiers()
        assert identifiers.next() != identifiers.next()


class TestPostgresCorpusIngestion:
    async def test_a_pending_document_is_inserted_not_updated(self) -> None:
        document = (
            Samples().corpus_document().model_copy(update={"review_status": "pending"})
        )
        connection = ScriptedConnection()
        ingested = await Wired().ingestion(connection, (_CHUNK,)).ingest(document)
        assert ingested.document_id == document.document_id
        assert ingested.chunk_ids == (_CHUNK,)
        assert connection.parameters[0]["review_status"] == "pending"
        assert all(
            statement.lstrip().upper().startswith("INSERT")
            for statement in connection.statements
        )
        assert all(
            "UPDATE" not in statement.upper() for statement in connection.statements
        )

    async def test_two_passages_are_two_chunks(self) -> None:
        document = (
            Samples()
            .corpus_document()
            .model_copy(update={"content": "The library is open.\n\nBring a notebook."})
        )
        connection = ScriptedConnection()
        ingested = (
            await Wired().ingestion(connection, (_CHUNK, _SECOND)).ingest(document)
        )
        assert ingested.chunk_ids == (_CHUNK, _SECOND)
        assert connection.parameters[1]["ordinal"] == 0
        assert connection.parameters[2]["ordinal"] == 1

    async def test_chunk_text_is_bound_as_ciphertext(self) -> None:
        connection = ScriptedConnection()
        await (
            Wired().ingestion(connection, (_CHUNK,)).ingest(Samples().corpus_document())
        )
        assert connection.parameters[1]["content"] == b"sealed:The library is open."

    def test_public_methods_are_ingest_only(self) -> None:
        public = [
            name
            for name in dir(PostgresCorpusIngestion)
            if not name.startswith("_")
            and callable(getattr(PostgresCorpusIngestion, name))
        ]
        assert public == ["ingest"]
