"""A knowledge-base document in the dataset (contract C1)."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

CefrLevel = Literal["A1", "A2", "B1", "B2", "C1", "C2"]
Partition = Literal["default", "faults"]
FaultKind = Literal["contradiction", "poisoned_unreviewed", "poisoned_approved"]
ReviewStatus = Literal["pending", "approved", "rejected"]


class KbDocumentRecord(BaseModel):
    """One document the seed may ingest. Poison carries a canary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: UUID
    source_uri: str = Field(min_length=1)
    version: str = Field(min_length=1)
    review_status: ReviewStatus
    licence: str = Field(min_length=1)
    cefr_level: CefrLevel
    level_method: str = Field(min_length=1)
    partition: Partition
    fault_kind: FaultKind | None = None
    canary: str | None = None
    topic_id: str = Field(min_length=1)
    content: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def content_has_a_passage(self) -> "KbDocumentRecord":
        """Whitespace is not a document."""
        if not self.content.strip():
            msg = "document has no passages"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def fault_matches_partition(self) -> "KbDocumentRecord":
        """The default partition has no fault. A fault names its kind."""
        if self.partition == "default" and self.fault_kind is not None:
            msg = "the default partition has no fault"
            raise ValueError(msg)
        if self.partition == "faults" and self.fault_kind is None:
            msg = "a fault document names its kind"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def canary_marks_poison(self) -> "KbDocumentRecord":
        """A canary is present exactly when the document is poisoned."""
        poisoned = self.fault_kind in {"poisoned_unreviewed", "poisoned_approved"}
        if poisoned and not self.canary:
            msg = "a poisoned document carries a canary"
            raise ValueError(msg)
        if not poisoned and self.canary is not None:
            msg = "only a poisoned document carries a canary"
            raise ValueError(msg)
        return self
