"""Unit of work commits, rolls back, and always closes the connection."""

import pytest

from tutor_api.adapters.persistence.unit_of_work import (
    SqlAlchemyUnitOfWork,
    TransactionConnection,
)
from tutor_core.domain.ports.unit_of_work import TransactionalWork


class RecordingConnection(TransactionConnection):
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False
        self.closed = False
        self.statements: list[str] = []

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def close(self) -> None:
        self.closed = True

    async def execute(self, statement: str) -> None:
        self.statements.append(statement)


class SucceedingWork(TransactionalWork):
    def __init__(self, connection: RecordingConnection) -> None:
        self._connection = connection

    async def run(self) -> None:
        await self._connection.execute("INSERT INTO example (id) VALUES (1)")


class FailingWork(TransactionalWork):
    async def run(self) -> None:
        raise RuntimeError("second write failed")


class TestSqlAlchemyUnitOfWork:
    async def test_commit_on_success_and_close(self) -> None:
        connection = RecordingConnection()
        await SqlAlchemyUnitOfWork(connection).run(SucceedingWork(connection))
        assert connection.committed
        assert not connection.rolled_back
        assert connection.closed
        assert connection.statements == ["INSERT INTO example (id) VALUES (1)"]

    async def test_rollback_on_failure_and_close(self) -> None:
        connection = RecordingConnection()
        with pytest.raises(RuntimeError, match="second write failed"):
            await SqlAlchemyUnitOfWork(connection).run(FailingWork())
        assert not connection.committed
        assert connection.rolled_back
        assert connection.closed
