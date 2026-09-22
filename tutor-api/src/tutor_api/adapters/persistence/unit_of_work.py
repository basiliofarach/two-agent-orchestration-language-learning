"""Commit one turn's writes, or roll them back, on an enlisted connection."""

from collections.abc import Mapping

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tutor_core.domain.ports.unit_of_work import (
    TransactionalWork,
    TransactionConnection,
    UnitOfWorkPort,
)


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

    async def fetch_one(
        self,
        statement: str,
        parameters: Mapping[str, object],
    ) -> tuple[object, ...] | None:
        result = await self._connection.execute(text(statement), dict(parameters))
        row = result.first()
        if row is None:
            return None
        return tuple(row)


class SqlAlchemyUnitOfWork(UnitOfWorkPort):
    """Run enlisted work and close the connection either way."""

    def __init__(self, connection: TransactionConnection) -> None:
        self._connection = connection

    async def run(self, work: TransactionalWork) -> None:
        # The work is handed this unit of work's connection, so it cannot be
        # writing to a different one that nothing here commits or closes.
        try:
            await work.run(self._connection)
            await self._connection.commit()
        except Exception:
            await self._connection.rollback()
            raise
        finally:
            await self._connection.close()
