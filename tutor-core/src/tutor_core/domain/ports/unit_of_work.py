"""One transaction for the writes that belong to a single turn."""

from abc import ABC, abstractmethod


class TransactionalWork(ABC):
    """Work that enlists in a unit of work.

    Scope boundary: the work receives an already-open connection. It does
    not open one (REQ-AUDIT, DEC-0006).
    """

    @abstractmethod
    async def run(self) -> None:
        """Perform the turn's writes on the enlisted connection."""
        raise NotImplementedError  # pragma: no cover


class UnitOfWorkPort(ABC):
    """Commit the turn's writes together, or roll them back together.

    Scope boundary: persistence adapters enlist in this transaction. They do
    not open a connection of their own (REQ-AUDIT, DEC-0006).
    """

    @abstractmethod
    async def run(self, work: TransactionalWork) -> None:
        """Run ``work``, commit on success, and roll back on failure."""
        raise NotImplementedError  # pragma: no cover
