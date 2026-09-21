"""Retrieval query and the sourced snippets it returns (REQ-KB)."""

from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RetrievalQuery(BaseModel):
    """Text the knowledge base may search. There is no URL and no web query."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=50)


class SourceRef(BaseModel):
    """Provenance that travels with a snippet (REQ-KB, DEC-0010).

    Frozen evidence: document identity, source, version, and review status.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: UUID
    source_uri: str = Field(min_length=1)
    version: str = Field(min_length=1)
    review_status: str = Field(min_length=1)


class Snippet(BaseModel):
    """One retrieved passage and the source it came from."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    content: str = Field(min_length=1)
    source: SourceRef
    ordinal: int = Field(ge=0)


class RetrievalResult(BaseModel):
    """Snippets, the sources they cite, and a confidence score."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    snippets: tuple[Snippet, ...]
    sources: tuple[SourceRef, ...]
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def sources_cover_snippets(self) -> Self:
        """Every snippet source is listed on the result."""
        for snippet in self.snippets:
            if snippet.source not in self.sources:
                msg = "every snippet source must appear in sources"
                raise ValueError(msg)
        return self
