"""Sessions and learners as the dashboard is allowed to see them (REQ-DASH)."""

from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tutor_core.domain.models.timestamps import AwareDatetime, Timestamped


class SessionSummary(Timestamped):
    """``tutor_id`` and ``stop_reason`` are not on this view (REQ-MINOR).

    The request role can select ``id``, ``learner_id``, ``started_at`` and
    ``stopped_at``. ``open`` is that last column being unset. The reason and
    the tutor stay unread.
    """

    session_id: UUID
    learner_id: UUID
    started_at: AwareDatetime
    stopped_at: AwareDatetime | None = None
    open: bool

    @model_validator(mode="after")
    def open_means_not_stopped(self) -> Self:
        """``open`` restates ``stopped_at``; the two never disagree."""
        if self.open != (self.stopped_at is None):
            msg = "a session is open exactly when it has no stop time"
            raise ValueError(msg)
        return self


class SessionOpening(Timestamped):
    """A session the dashboard asked to open, before it is written.

    ``tutor_id`` is sealed by the adapter; it is never readable back from
    the request path (REQ-MINOR).
    """

    session_id: UUID
    learner_id: UUID
    tutor_id: str = Field(min_length=1)
    started_at: AwareDatetime


class LearnerSummary(BaseModel):
    """A learner a session can be opened for: the pseudonymous id only.

    ``pseudonym`` is not granted to the request role, so it is not here.
    ``retained`` is false once ``retain_until`` has passed: such a learner
    cannot be given a new session.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    learner_id: UUID
    retained: bool
