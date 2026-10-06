"""Retrieval query and the sourced snippets it returns (REQ-KB)."""

from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tutor_core.domain.models.learner import LearnerHistorySnapshot
from tutor_core.domain.models.safety import RedactedText


class RedactedRetrievalRequest(BaseModel):
    """Retrieval the pipeline may run. The prompt is already redacted.

    Downstream of the input boundary the signature takes ``RedactedText``,
    not a raw learner string (REQ-MINOR). The knowledge base searches this
    text. There is no URL and no web query.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt: RedactedText
    limit: int = Field(default=5, ge=1, le=50)

    @model_validator(mode="after")
    def prompt_has_text(self) -> Self:
        """An empty prompt is not a query."""
        if not self.prompt.text:
            msg = "retrieval request has no text"
            raise ValueError(msg)
        return self


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
    """One retrieved passage and the source it came from.

    ``chunk_id`` is the ``kb_chunk`` row this passage was read from.
    ``TurnAuditRecord.retrieved_context_ids`` stores that identifier, and
    ``turn_citation.chunk_id`` references it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: UUID
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


class RetrievedContext(BaseModel):
    """Vetted snippets and the allowlisted history that came with them.

    An empty ``knowledge`` result is valid. It is not an error and not
    ``None`` (REQ-KB). History may withhold fields; that absence is on
    the snapshot (REQ-HISTORY).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    knowledge: RetrievalResult
    history: LearnerHistorySnapshot
