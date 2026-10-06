"""List, read and open the sessions the dashboard works in."""

from abc import ABC, abstractmethod
from uuid import UUID

from tutor_core.domain.models.session import (
    LearnerSummary,
    SessionOpening,
    SessionSummary,
)


class SessionNotFound(LookupError):
    """No session has this id. The route answers 404 and reads nothing more."""


class SessionOpenRejected(Exception):
    """The learner is not known, or their retention has ended (REQ-MINOR).

    The database refuses the insert, so nothing is written. A purged
    learner cannot be given a new session.
    """


class SessionDirectoryPort(ABC):
    """Sessions for the adult tutor (REQ-DASH, REQ-MINOR).

    Scope boundary: the columns a dashboard may see (``id``,
    ``learner_id``, ``started_at``, ``stopped_at``) and the learner id. A
    session is opened through the database's ``open_session`` function, so
    the port holds no INSERT on the table and cannot change a session once
    opened. Stopping one is ``HumanActionPort``, not this port, because a
    stop must be a logged tutor action.
    """

    @abstractmethod
    async def listed(self) -> tuple[SessionSummary, ...]:
        """Return every session, most recently started first."""
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def get(self, session_id: UUID) -> SessionSummary | None:
        """Return one session, or ``None`` when it is not known."""
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def open(self, opening: SessionOpening) -> None:
        """Open the session. Raise ``SessionOpenRejected`` when refused."""
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def learners(self) -> tuple[LearnerSummary, ...]:
        """Return every learner a session could name, by pseudonymous id."""
        raise NotImplementedError  # pragma: no cover
