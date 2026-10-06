"""A session as the dashboard is allowed to see it (REQ-DASH)."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SessionSummary(BaseModel):
    """``tutor_id`` and ``stop_reason`` are not on this view (REQ-MINOR).

    The request role can select ``id``, ``learner_id`` and ``stopped_at``.
    ``open`` is that last column being unset. The reason and the tutor stay
    unread.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: UUID
    learner_id: UUID
    open: bool
