"""One admitted source. The digest is checked at every fetch (DEC-0016)."""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

LicenceReview = Literal["pending", "confirmed", "rejected"]
SourceUse = Literal["kb", "grounding", "payload", "tool"]


class SourceRecord(BaseModel):
    """A pinned source and the licence reading recorded against it.

    ``redirect_hosts`` names the hosts the pinned URL may redirect to, such
    as a Hugging Face or GitHub CDN. They join the fetch allowlist; a hop to
    any other host is refused.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str = Field(min_length=1, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    licence: str = Field(min_length=1)
    licence_url: str = Field(min_length=1)
    redistributable: bool
    use: SourceUse
    attribution: str = Field(min_length=1)
    redirect_hosts: tuple[
        Annotated[str, Field(pattern=r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")], ...
    ] = ()
    licence_review: LicenceReview = "pending"
    reviewed_by: str | None = None
    reviewed_on: date | None = None
    review_note: str | None = None

    @model_validator(mode="after")
    def revision_is_pinned(self) -> "SourceRecord":
        """A floating revision cannot be reproduced."""
        if self.revision == "latest":
            msg = "revision must be pinned"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def review_fields_move_together(self) -> "SourceRecord":
        """A pending review has no reviewer. A decision names who and when."""
        decided = (self.reviewed_by, self.reviewed_on, self.review_note)
        if self.licence_review == "pending":
            if any(part is not None for part in decided):
                msg = "a pending review has no reviewer"
                raise ValueError(msg)
            return self
        if any(part is None for part in decided):
            msg = "a decided review names the reviewer, the date, and a note"
            raise ValueError(msg)
        return self
