"""Construct the async engine when a caller asks. Nothing is created at import."""

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from tutor_api.adapters.persistence.unit_of_work import SqlAlchemyConnection


class DatabaseEngine:
    """Injected engine provider. The engine exists only on this instance."""

    def __init__(self, url: str) -> None:
        self._engine: AsyncEngine = create_async_engine(url)

    async def connect(self) -> SqlAlchemyConnection:
        connection = await self._engine.connect()
        return SqlAlchemyConnection(connection)

    async def dispose(self) -> None:
        await self._engine.dispose()
