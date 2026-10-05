"""In-memory ``TransactionConnection`` for persistence adapter unit tests."""

from collections.abc import Mapping

from tutor_core.domain.ports.unit_of_work import TransactionConnection


class ScriptedConnection(TransactionConnection):
    """Return the rows it was given and record every statement."""

    def __init__(self, rows: tuple[tuple[object, ...], ...] = ()) -> None:
        self.statements: list[str] = []
        self.parameters: list[dict[str, object]] = []
        self._rows = rows

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def execute(
        self,
        statement: str,
        parameters: Mapping[str, object] | None = None,
    ) -> None:
        self._record(statement, parameters or {})

    async def fetch_one(
        self,
        statement: str,
        parameters: Mapping[str, object],
    ) -> tuple[object, ...] | None:
        self._record(statement, parameters)
        if not self._rows:
            return None
        return self._rows[0]

    async def fetch_all(
        self,
        statement: str,
        parameters: Mapping[str, object],
    ) -> tuple[tuple[object, ...], ...]:
        self._record(statement, parameters)
        return self._rows

    def _record(self, statement: str, parameters: Mapping[str, object]) -> None:
        self.statements.append(statement)
        self.parameters.append(dict(parameters))
