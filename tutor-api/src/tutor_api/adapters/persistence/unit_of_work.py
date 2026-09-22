"""Commit one turn's writes, or roll them back, on an enlisted connection."""

from abc import ABC, abstractmethod
from collections.abc import Mapping

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tutor_core.domain.ports.unit_of_work import TransactionalWork, UnitOfWorkPort


class TransactionConnection(ABC):
    """The commit, rollback, and close operations a unit of work needs."""

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


class SqlAlchemyConnection(TransactionConnection):
    """Async SQLAlchemy connection behind ``TransactionConnection``."""

    def __init__(self, connection: AsyncConnection) -> None:
        self._connection = connection

    async def commit(self) -> None:
        await self._connection.commit()

    async def rollback(self) -> None:
        await self._connection.rollback()

    async def close(self) -> None:
        await self._connection.close()

    async def execute(
        self,
        statement: str,
        parameters: Mapping[str, object] | None = None,
    ) -> None:
        await self._connection.execute(text(statement), dict(parameters or {}))


class SqlAlchemyUnitOfWork(UnitOfWorkPort):
    """Run enlisted work and close the connection either way."""

    def __init__(self, connection: TransactionConnection) -> None:
        self._connection = connection

    async def run(self, work: TransactionalWork) -> None:
        try:
            await work.run()
            await self._connection.commit()
        except Exception:
            await self._connection.rollback()
            raise
        finally:
            await self._connection.close()
