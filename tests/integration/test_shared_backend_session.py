"""Two coroutines on one request connection share the backend session."""

import asyncio

from tests.support.migrated_database import PostgresUrl

from tutor_api.adapters.persistence.database import DatabaseEngine, RequestConnection


class BackendPid:
    """``pg_backend_pid`` of the session a statement ran on."""

    async def of(self, connection: RequestConnection) -> int:
        row = await connection.fetch_one("SELECT pg_backend_pid()", {})
        assert row is not None
        return int(str(row[0]))


class TestConcurrentRequestConnection:
    async def test_two_coroutines_share_one_backend_session(
        self, fresh_database: str
    ) -> None:
        engine = DatabaseEngine(PostgresUrl(fresh_database).async_url())
        connection = RequestConnection(engine)
        try:
            pid = BackendPid()
            first, second = await asyncio.gather(
                pid.of(connection),
                pid.of(connection),
            )
        finally:
            await connection.close()
            await engine.dispose()
        assert first == second
