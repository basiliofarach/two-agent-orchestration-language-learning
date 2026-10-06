"""Read the audit log. No insert, update, or delete."""

from abc import ABC, abstractmethod
from uuid import UUID

from tutor_core.domain.models.audit import HumanAction, TurnAuditRecord


class AuditQueryPort(ABC):
    """Read sealed turn records and the tutor actions after them (REQ-AUDIT).

    Scope boundary: read-only. The generation path appends through
    ``AuditSinkPort`` and does not hold this port, so a prompt cannot ask
    the model to walk another learner’s log. Ciphertext is opened here,
    after redaction has already run, and the opened prompt is the redacted
    one (REQ-MINOR).
    """

    @abstractmethod
    async def for_session(self, session_id: UUID) -> tuple[TurnAuditRecord, ...]:
        """Return the session’s records in chain order."""
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def turn(self, turn_id: UUID) -> TurnAuditRecord | None:
        """Return one record, or ``None`` when the turn was not logged."""
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def actions(self, turn_id: UUID) -> tuple[HumanAction, ...]:
        """Return the tutor actions appended after ``turn_id``, in time order."""
        raise NotImplementedError  # pragma: no cover
