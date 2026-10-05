"""Reviewed chunks are retrievable through pgvector, with their provenance."""

from typing import Literal
from uuid import UUID

import psycopg
from tests.support.curation import Curator
from tests.support.migrated_database import MigratedDatabase, PostgresUrl
from tests.support.samples import Samples

from tutor_api.adapters.persistence.aes_gcm_envelope import AesGcmEnvelope
from tutor_core.domain.models.corpus import CorpusDocument

_APPROVED = UUID("00000000-0000-4000-8000-000000000070")
_PENDING = UUID("00000000-0000-4000-8000-000000000071")
_SECOND = UUID("00000000-0000-4000-8000-000000000072")
_REJECTED = UUID("00000000-0000-4000-8000-000000000073")
_TEXT = "The library is open."


class Documents:
    def of(
        self,
        document_id: UUID,
        version: str,
        status: Literal["pending", "approved", "rejected"],
    ) -> CorpusDocument:
        return CorpusDocument(
            document_id=document_id,
            source_uri="kb://library",
            version=version,
            review_status=status,
            content=_TEXT,
        )


class TestKnowledgeBase:
    def _curator(self, url: str) -> Curator:
        MigratedDatabase().upgrade(url)
        cipher = AesGcmEnvelope(key=bytes(range(32)), key_id=UUID(int=1))
        return Curator(PostgresUrl(url).async_url(), cipher)

    async def test_unreviewed_documents_are_not_retrievable(
        self, fresh_database: str
    ) -> None:
        curator = self._curator(fresh_database)
        await curator.ingest(Documents().of(_APPROVED, "1", "approved"))
        await curator.ingest(Documents().of(_PENDING, "1", "pending"))
        await curator.ingest(Documents().of(_REJECTED, "1", "rejected"))
        result = await curator.retrieve(Samples().redacted_request(_TEXT))
        assert [snippet.source.document_id for snippet in result.snippets] == [
            _APPROVED
        ]
        assert result.snippets[0].source.review_status == "approved"
        assert result.confidence > 0.0

    async def test_every_snippet_carries_its_source_metadata(
        self, fresh_database: str
    ) -> None:
        curator = self._curator(fresh_database)
        await curator.ingest(Documents().of(_APPROVED, "3", "approved"))
        result = await curator.retrieve(Samples().redacted_request(_TEXT))
        snippet = result.snippets[0]
        assert snippet.content == _TEXT
        assert snippet.source.document_id == _APPROVED
        assert snippet.source.source_uri == "kb://library"
        assert snippet.source.version == "3"
        assert snippet.source.review_status == "approved"

    async def test_empty_retrieval_returns_a_result_not_an_exception(
        self, fresh_database: str
    ) -> None:
        result = await self._curator(fresh_database).retrieve(
            Samples().redacted_request("library")
        )
        assert result.snippets == ()
        assert result.sources == ()
        assert result.confidence == 0.0

    async def test_reingesting_a_source_inserts_a_new_version(
        self, fresh_database: str
    ) -> None:
        curator = self._curator(fresh_database)
        await curator.ingest(Documents().of(_APPROVED, "1", "approved"))
        await curator.ingest(Documents().of(_SECOND, "2", "approved"))
        with psycopg.connect(fresh_database) as connection:
            rows = connection.execute(
                "SELECT id, version FROM kb_document ORDER BY version"
            ).fetchall()
        assert rows == [(_APPROVED, "1"), (_SECOND, "2")]

    async def test_chunk_text_is_ciphertext_at_rest(self, fresh_database: str) -> None:
        curator = self._curator(fresh_database)
        await curator.ingest(Documents().of(_APPROVED, "1", "approved"))
        with psycopg.connect(fresh_database) as connection:
            row = connection.execute("SELECT content FROM kb_chunk").fetchone()
        assert row is not None
        assert _TEXT.encode("utf-8") not in bytes(row[0])
