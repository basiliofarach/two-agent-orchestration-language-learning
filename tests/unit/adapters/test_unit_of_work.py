"""Unit of work commits, rolls back, and always closes the connection."""

from collections.abc import Mapping

import pytest

from tutor_api.adapters.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tutor_core.domain.ports.unit_of_work import (
    TransactionalWork,
    TransactionConnection,
)


class RecordingConnection(TransactionConnection):
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False
        self.closed = False
        self.statements: list[str] = []
        self.parameters: list[Mapping[str, object]] = []
        self.rows: list[tuple[object, ...]] = []
        self.fetches: list[tuple[str, Mapping[str, object]]] = []

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def close(self) -> None:
        self.closed = True

    async def execute(
        self,
        statement: str,
        parameters: Mapping[str, object] | None = None,
    ) -> None:
        self.statements.append(statement)
        self.parameters.append(dict(parameters or {}))

    async def fetch_one(
        self,
        statement: str,
        parameters: Mapping[str, object],
    ) -> tuple[object, ...] | None:
        self.fetches.append((statement, dict(parameters)))
        if not self.rows:
            return None
        return self.rows.pop(0)


class SucceedingWork(TransactionalWork):
    async def run(self, connection: TransactionConnection) -> None:
        await connection.execute(
            "INSERT INTO example (id) VALUES (:id)",
            {"id": 1},
        )


class FailingWork(TransactionalWork):
    async def run(self, connection: TransactionConnection) -> None:
        raise RuntimeError("second write failed")


class TestSqlAlchemyUnitOfWork:
    async def test_commit_on_success_and_close(self) -> None:
        connection = RecordingConnection()
        await SqlAlchemyUnitOfWork(connection).run(SucceedingWork())
        assert connection.committed
        assert not connection.rolled_back
        assert connection.closed
        assert connection.statements == ["INSERT INTO example (id) VALUES (:id)"]
        assert connection.parameters == [{"id": 1}]

    async def test_rollback_on_failure_and_close(self) -> None:
        connection = RecordingConnection()
        with pytest.raises(RuntimeError, match="second write failed"):
            await SqlAlchemyUnitOfWork(connection).run(FailingWork())
        assert not connection.committed
        assert connection.rolled_back
        assert connection.closed


class TestBoundParameters:
    async def test_values_are_bound_not_interpolated(self) -> None:
        connection = RecordingConnection()
        await connection.execute(
            "INSERT INTO example (name) VALUES (:name)",
            {"name": "Robert'); DROP TABLE example;--"},
        )
        assert connection.statements == ["INSERT INTO example (name) VALUES (:name)"]
        assert "DROP TABLE" not in connection.statements[0]
        assert connection.parameters == [{"name": "Robert'); DROP TABLE example;--"}]


class EnlistmentProbe(TransactionalWork):
    """Records which connection it was handed."""

    def __init__(self) -> None:
        self.received: TransactionConnection | None = None

    async def run(self, connection: TransactionConnection) -> None:
        self.received = connection


class TestEnlistment:
    async def test_work_runs_on_the_committed_connection(self) -> None:
        """The work cannot be writing to a connection nobody commits.

        Before the connection was a parameter, work built against one
        connection could be handed to a unit of work that commits another:
        the first connection's writes were neither committed nor closed.
        """
        committed = RecordingConnection()
        probe = EnlistmentProbe()
        await SqlAlchemyUnitOfWork(committed).run(probe)
        assert probe.received is committed
        assert committed.committed
