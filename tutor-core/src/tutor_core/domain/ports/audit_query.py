"""Read the audit log. No insert, update, or delete."""

from abc import ABC, abstractmethod
from uuid import UUID

from tutor_core.domain.models.audit import HumanAction, TurnAuditRecord
from tutor_core.domain.models.retrieval import Snippet


class TurnNotFound(LookupError):
    """No turn has this id, or it is not in the session the caller named."""


class AuditRecordUnreadable(Exception):
    """A stored turn no longer validates as a record.

    The table is append-only to the application role, but INSERT is
    granted, so an extra gate row can make a turn fail validation. That is
    evidence of tampering, reported on ``turn_id``, not a server error.
    """

    def __init__(self, turn_id: UUID) -> None:
        super().__init__(f"audit record {turn_id} no longer validates")
        self.turn_id = turn_id


class AuditQueryPort(ABC):
    """Read sealed turn records and the tutor actions after them (REQ-AUDIT).

    Scope boundary: read-only. The generation path appends through
    ``AuditSinkPort`` and does not hold this port, so a prompt cannot ask
    the model to walk another learner's log. Ciphertext is opened here,
    after redaction has already run, and the opened prompt is the redacted
    one (REQ-MINOR).
    """

    @abstractmethod
    async def for_session(self, session_id: UUID) -> tuple[TurnAuditRecord, ...]:
        """Return the session's records in chain order.

        A record that no longer validates raises ``AuditRecordUnreadable``.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def turn(self, turn_id: UUID) -> TurnAuditRecord | None:
        """Return one record, or ``None`` when the turn was not logged."""
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def actions(self, turn_id: UUID) -> tuple[HumanAction, ...]:
        """Return the tutor actions appended after ``turn_id``, in time order."""
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def session_actions(self, session_id: UUID) -> tuple[HumanAction, ...]:
        """Return every tutor action in the session, in append order."""
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def citations(self, turn_id: UUID) -> tuple[Snippet, ...]:
        """Return the vetted chunks the turn cited, in citation order.

        The chunk text is curated material, not learner text (DEC-0012),
        so the dashboard can show what the draft was grounded in.
        """
        raise NotImplementedError  # pragma: no cover
