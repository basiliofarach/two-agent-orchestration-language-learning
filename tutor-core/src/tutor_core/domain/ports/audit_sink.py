"""Append one immutable turn record. No update and no delete."""

from abc import ABC, abstractmethod

from tutor_core.domain.models.audit import TurnAuditRecord


class AuditSinkPort(ABC):
    """Append one immutable turn record (REQ-AUDIT).

    Scope boundary: append-only. This port declares ``append()`` and nothing
    else — no update, no delete, no upsert. That absence is the Article 12
    claim.
    """

    @abstractmethod
    async def append(self, record: TurnAuditRecord) -> None:
        """Append ``record`` on the enlisted transaction.

        There is no method that changes a written row. The adapter writes on
        the connection it was given, so this row commits or rolls back with
        the work it describes.
        """
        raise NotImplementedError  # pragma: no cover
