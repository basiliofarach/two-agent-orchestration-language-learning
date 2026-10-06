"""Append one immutable turn record. No update and no delete."""

from abc import ABC, abstractmethod
from uuid import UUID

from tutor_core.domain.models.audit import ChainHead, TurnAuditRecord


class AuditSinkPort(ABC):
    """Append one immutable turn record (REQ-AUDIT).

    Scope boundary: append-only. This port declares ``append()`` and the
    read ``head()`` the next record links to — no update, no delete, no
    upsert. That absence is the Article 12 claim.
    """

    @abstractmethod
    async def head(self, session_id: UUID) -> ChainHead:
        """Return where the next record of ``session_id`` attaches.

        Read on the enlisted transaction. ``append`` re-checks the link under
        the session lock, so a concurrent append is rejected, not forked.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def append(self, record: TurnAuditRecord) -> None:
        """Append ``record`` on the enlisted transaction.

        There is no method that changes a written row. The adapter writes on
        the connection it was given, so this row commits or rolls back with
        the work it describes.
        """
        raise NotImplementedError  # pragma: no cover
