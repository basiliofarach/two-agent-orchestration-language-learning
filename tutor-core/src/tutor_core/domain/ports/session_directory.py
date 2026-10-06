"""List sessions the dashboard can open. No insert and no update."""

from abc import ABC, abstractmethod
from uuid import UUID

from tutor_core.domain.models.session import SessionSummary


class SessionDirectoryPort(ABC):
    """List tutoring sessions for the adult tutor (REQ-DASH, REQ-MINOR).

    Scope boundary: read-only, and only the columns the turn check may
    already see (``id``, ``learner_id``, ``stopped_at``). Opening a session
    stays on the operator seed. Stopping one is ``HumanActionPort``, not
    this port.
    """

    @abstractmethod
    async def listed(self) -> tuple[SessionSummary, ...]:
        """Return every session, open ones and stopped ones."""
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def get(self, session_id: UUID) -> SessionSummary | None:
        """Return one session, or ``None`` when it is not known."""
        raise NotImplementedError  # pragma: no cover
