"""Construct the async engine when a caller asks. Nothing is created at import."""

from collections.abc import Mapping

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from tutor_api.adapters.persistence.unit_of_work import SqlAlchemyConnection
from tutor_core.domain.ports.unit_of_work import TransactionConnection


class DatabaseEngine:
    """Injected engine provider. The engine exists only on this instance."""

    def __init__(self, url: str) -> None:
        self._engine: AsyncEngine = create_async_engine(url)

    async def connect(self) -> TransactionConnection:
        connection = await self._engine.connect()
        return SqlAlchemyConnection(connection)

    async def dispose(self) -> None:
        await self._engine.dispose()


class RequestConnection(TransactionConnection):
    """The one connection a request's adapters and unit of work share.

    Request-scoped (DEC-0014). Providers are synchronous and connecting is
    not, so the connection opens on first use. Knowledge base, policy, audit
    sink and unit of work all hold this object, so retrieval and the audit
    row it describes run on one transaction (DEC-0006).

    Commit, rollback and close before first use are no-ops: nothing was
    opened, so there is nothing to end.
    """

    def __init__(self, engine: DatabaseEngine) -> None:
        self._engine = engine
        self._opened: TransactionConnection | None = None

    async def commit(self) -> None:
        if self._opened is not None:
            await self._opened.commit()

    async def rollback(self) -> None:
        if self._opened is not None:
            await self._opened.rollback()

    async def close(self) -> None:
        if self._opened is not None:
            await self._opened.close()
            self._opened = None

    async def execute(
        self,
        statement: str,
        parameters: Mapping[str, object] | None = None,
    ) -> None:
        await (await self._open()).execute(statement, parameters)

    async def fetch_one(
        self,
        statement: str,
        parameters: Mapping[str, object],
    ) -> tuple[object, ...] | None:
        return await (await self._open()).fetch_one(statement, parameters)

    async def fetch_all(
        self,
        statement: str,
        parameters: Mapping[str, object],
    ) -> tuple[tuple[object, ...], ...]:
        return await (await self._open()).fetch_all(statement, parameters)

    async def _open(self) -> TransactionConnection:
        if self._opened is None:
            self._opened = await self._engine.connect()
        return self._opened
