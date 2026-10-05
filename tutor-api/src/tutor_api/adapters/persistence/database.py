"""Construct the async engine when a caller asks. Nothing is created at import."""

import asyncio
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


class RequestConnectionClosed(Exception):
    """The request's connection was closed. A request does not get a second."""


class RequestConnection(TransactionConnection):
    """The one connection a request's adapters and unit of work share.

    Request-scoped (DEC-0014). Providers are synchronous and connecting is
    not, so the connection opens on first use. Knowledge base, policy, audit
    sink and unit of work all hold this object, so retrieval and the audit
    row it describes run on one transaction (DEC-0006).

    Commit, rollback and close before first use are no-ops: nothing was
    opened, so there is nothing to end.

    Close is final, whether or not anything was opened. A statement or a
    commit after it raises ``RequestConnectionClosed`` instead of opening a
    second connection, which would run outside the transaction the unit of
    work already ended and which nothing would commit or close. Rollback and
    close after close are no-ops, so cleanup paths stay safe to repeat.

    Opening is serialized. Two coroutines can both observe that nothing is
    open yet; without the lock each would connect, and one connection would
    be dropped. Close takes the same lock, so it cannot return while a
    connect is still in flight and then leave that connection unclosed.
    The lock is held for the statement too: one asyncpg connection cannot
    run two operations at once.
    """

    def __init__(self, engine: DatabaseEngine) -> None:
        self._engine = engine
        self._opened: TransactionConnection | None = None
        self._closed = False
        self._gate = asyncio.Lock()

    async def commit(self) -> None:
        async with self._gate:
            self._require_open()
            if self._opened is not None:
                await self._opened.commit()

    async def rollback(self) -> None:
        async with self._gate:
            if self._opened is not None:
                await self._opened.rollback()

    async def close(self) -> None:
        async with self._gate:
            opened = self._opened
            self._opened = None
            self._closed = True
            if opened is not None:
                await opened.close()

    async def execute(
        self,
        statement: str,
        parameters: Mapping[str, object] | None = None,
    ) -> None:
        async with self._gate:
            await (await self._open()).execute(statement, parameters)

    async def fetch_one(
        self,
        statement: str,
        parameters: Mapping[str, object],
    ) -> tuple[object, ...] | None:
        async with self._gate:
            return await (await self._open()).fetch_one(statement, parameters)

    async def fetch_all(
        self,
        statement: str,
        parameters: Mapping[str, object],
    ) -> tuple[tuple[object, ...], ...]:
        async with self._gate:
            return await (await self._open()).fetch_all(statement, parameters)

    async def _open(self) -> TransactionConnection:
        """Open once. The caller holds ``_gate``; this lock is not reentrant."""
        self._require_open()
        if self._opened is None:
            self._opened = await self._engine.connect()
        return self._opened

    def _require_open(self) -> None:
        if self._closed:
            msg = "the request connection is already closed"
            raise RequestConnectionClosed(msg)
