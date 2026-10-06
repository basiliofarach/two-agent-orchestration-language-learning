"""Append one tutor decision. No update and no delete."""

from abc import ABC, abstractmethod
from uuid import UUID

from tutor_core.domain.models.audit import ActionChainHead, HumanAction


class ActionRejected(Exception):
    """The session or the turn cannot take this action (REQ-DASH).

    A stopped session, a second decision on one turn, an approval of a turn
    the model never ran on, or a chain link that a concurrent action
    overtook. The insert rolls back with the unit of work, so a rejected
    stop leaves the session open and writes no row (REQ-AUDIT).
    """


class HumanActionPort(ABC):
    """Append the tutor's approve, edit, override, or stop (REQ-DASH, REQ-AUDIT).

    Scope boundary: append-only, and only after the turn row exists. This
    port cannot change ``turn_audit``. A ``stop`` also marks the session
    stopped, in the same transaction, so the session preserves the turns it
    already has and accepts no further one (ARCHITECTURE §8.3). Actions are
    chained per session like turns, so the port reports where the next one
    attaches.
    """

    @abstractmethod
    async def head(self, session_id: UUID) -> ActionChainHead:
        """Where the next action of ``session_id`` attaches. Read only."""
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def append(self, action: HumanAction) -> None:
        """Append a chained ``action``.

        Async because the insert uses the request's one connection
        (DEC-0014). Anything the database refuses — the guard trigger, the
        one-decision index, or a stale chain link — raises
        ``ActionRejected``.
        """
        raise NotImplementedError  # pragma: no cover
