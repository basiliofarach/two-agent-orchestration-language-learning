"""A curated document and the chunks ingestion stored for it (REQ-KB)."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

ReviewStatus = Literal["pending", "approved", "rejected"]


class CorpusDocument(BaseModel):
    """Source, version, and review status recorded at ingestion (REQ-KB).

    ``review_status`` has no default. A missing status is a refusal, not an
    assumption that the document was reviewed.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: UUID
    source_uri: str = Field(min_length=1)
    version: str = Field(min_length=1)
    review_status: ReviewStatus
    content: str = Field(min_length=1)

    @field_validator("content")
    @classmethod
    def content_has_a_passage(cls, value: str) -> str:
        """Whitespace is not a document."""
        if not value.strip():
            msg = "document has no passages"
            raise ValueError(msg)
        return value


class IngestedDocument(BaseModel):
    """The row ids ingestion inserted. Re-ingestion allocates new ids."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: UUID
    chunk_ids: tuple[UUID, ...]
