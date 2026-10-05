"""The request connection opens on first use, once, and ends what it opened."""

from tests.unit.adapters.test_unit_of_work import RecordingConnection

from tutor_api.adapters.persistence.database import DatabaseEngine, RequestConnection
from tutor_core.domain.ports.unit_of_work import TransactionConnection


class CountingEngine(DatabaseEngine):
    """Hands out recording connections and counts how many were taken."""

    def __init__(self) -> None:
        super().__init__("postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")
        self.opened: list[RecordingConnection] = []

    async def connect(self) -> TransactionConnection:
        connection = RecordingConnection()
        self.opened.append(connection)
        return connection


class TestRequestConnection:
    async def test_nothing_is_opened_until_first_use(self) -> None:
        engine = CountingEngine()
        connection = RequestConnection(engine)
        await connection.commit()
        await connection.rollback()
        await connection.close()
        assert engine.opened == []

    async def test_every_statement_in_a_request_uses_one_connection(self) -> None:
        engine = CountingEngine()
        connection = RequestConnection(engine)
        await connection.execute("SELECT 1")
        await connection.fetch_one("SELECT 2", {})
        await connection.fetch_all("SELECT 3", {})
        assert len(engine.opened) == 1
        assert engine.opened[0].statements == ["SELECT 1"]
        assert [fetch[0] for fetch in engine.opened[0].fetches] == [
            "SELECT 2",
            "SELECT 3",
        ]

    async def test_commit_rollback_and_close_reach_the_opened_connection(
        self,
    ) -> None:
        engine = CountingEngine()
        connection = RequestConnection(engine)
        await connection.execute("SELECT 1")
        await connection.commit()
        await connection.rollback()
        await connection.close()
        opened = engine.opened[0]
        assert opened.committed
        assert opened.rolled_back
        assert opened.closed

    async def test_after_close_the_next_use_takes_a_new_connection(self) -> None:
        engine = CountingEngine()
        connection = RequestConnection(engine)
        await connection.execute("SELECT 1")
        await connection.close()
        await connection.execute("SELECT 2")
        assert len(engine.opened) == 2
