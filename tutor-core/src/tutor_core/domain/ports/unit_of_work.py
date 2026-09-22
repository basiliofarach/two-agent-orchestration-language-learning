"""One transaction for the writes that belong to a single turn."""

from abc import ABC, abstractmethod
from collections.abc import Mapping


class TransactionConnection(ABC):
    """The commit, rollback, close and execute a unit of work needs.

    Scope boundary: the operations a turn's writes need and nothing more —
    no connect, no engine, no cursor. A collaborator holding one of these
    cannot open a second transaction (REQ-AUDIT, DEC-0006).

    Declared in the domain because ``TransactionalWork.run`` receives one: an
    adapter-side interface could not appear in a domain signature without the
    domain importing infrastructure, which the layering forbids. The
    implementation stays in ``tutor_api`` (DEC-0001).
    """

    @abstractmethod
    async def commit(self) -> None:
        """Commit the enlisted transaction."""
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def rollback(self) -> None:
        """Roll back the enlisted transaction."""
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def close(self) -> None:
        """Return the connection. Called on both success and failure."""
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def execute(
        self,
        statement: str,
        parameters: Mapping[str, object] | None = None,
    ) -> None:
        """Run one statement on the enlisted connection.

        Values are bound, never interpolated into ``statement``. Without a
        parameter channel the only way to write learner or model data would be
        to build the SQL by string formatting, which is an injection path this
        signature exists to close.
        """
        raise NotImplementedError  # pragma: no cover


class TransactionalWork(ABC):
    """Work that enlists in a unit of work.

    Scope boundary: the work receives an already-open connection and does not
    open one (REQ-AUDIT, DEC-0006).

    The connection is a parameter, not something the work closes over. With
    the work holding its own, a caller could build it against one connection
    and hand it to a unit of work that commits another: the first
    connection's writes would be neither committed nor closed while the
    second committed, and the single-transaction guarantee behind REQ-AUDIT
    would be silently untrue. Passing it makes enlistment structural
    (DEC-0006).
    """

    @abstractmethod
    async def run(self, connection: TransactionConnection) -> None:
        """Perform the turn's writes on the connection it is given."""
        raise NotImplementedError  # pragma: no cover


class UnitOfWorkPort(ABC):
    """Commit the turn's writes together, or roll them back together.

    Scope boundary: persistence adapters enlist in this transaction. They do
    not open a connection of their own (REQ-AUDIT, DEC-0006).
    """

    @abstractmethod
    async def run(self, work: TransactionalWork) -> None:
        """Run ``work`` on this transaction, committing or rolling back."""
        raise NotImplementedError  # pragma: no cover
