"""Append one tutor decision. No update and no delete."""

from abc import ABC, abstractmethod
from uuid import UUID

from tutor_core.domain.models.audit import HumanAction


class ActionRejected(Exception):
    """The action does not belong on this turn, or the session cannot take it.

    The insert rolls back with the unit of work, so a rejected stop leaves
    the session open and writes no row (REQ-DASH, REQ-AUDIT).
    """


class HumanActionPort(ABC):
    """Append the tutor’s approve, edit, override, or stop (REQ-DASH, REQ-AUDIT).

    Scope boundary: append-only, and only after the turn row exists. This
    port cannot change ``turn_audit``. A ``stop`` also marks the session
    stopped, in the same transaction, so the session preserves the turns it
    already has and accepts no further one (ARCHITECTURE §8.3).
    """

    @abstractmethod
    async def append(self, action: HumanAction, session_id: UUID) -> None:
        """Append ``action`` for a turn in ``session_id``.

        Async because the insert uses the request’s one connection
        (DEC-0014). A stop that the database refuses raises
        ``ActionRejected``.
        """
        raise NotImplementedError  # pragma: no cover
