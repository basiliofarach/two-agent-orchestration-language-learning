"""Confirm a session can take this learner's turn, before any read."""

from abc import ABC, abstractmethod
from uuid import UUID

from tutor_core.domain.models.learner import LearnerId


class SessionRejected(Exception):
    """The session is missing, stopped, or another learner's.

    Raised before retrieval. The turn rolls back, so nothing is read for
    the model and nothing is written under the session (REQ-MINOR).
    """


class TutoringSessionPort(ABC):
    """Confirm one session can take this learner's turn (REQ-MINOR, REQ-AUDIT).

    Scope boundary: read-only. The port can confirm that a session exists,
    is still open, and belongs to the learner. It cannot open, stop, or
    reassign a session. The check runs on the enlisted connection, before
    retrieval, so one learner's history cannot be read into another's
    session and then audited there.
    """

    @abstractmethod
    async def require_active(self, session_id: UUID, learner_id: LearnerId) -> None:
        """Raise ``SessionRejected`` unless this session can take the turn.

        A missing session, a session with ``stopped_at`` set, and a session
        whose learner is not ``learner_id`` are the same kind of refusal:
        the turn does not start. Async because the read uses the request's
        one connection (DEC-0014).
        """
        raise NotImplementedError  # pragma: no cover
