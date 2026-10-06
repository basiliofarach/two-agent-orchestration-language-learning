"""Shared enlisted connection for a persistence adapter.

The first project’s repository base adds, loads and deletes ORM rows. This
store is SQLAlchemy Core on one request connection (DEC-0014), so the shared
base is those three operations and nothing that would become a second public
API. A concrete adapter’s public methods stay exactly its port’s methods
(DEC-0011).
"""

from collections.abc import Mapping

from tutor_core.domain.ports.unit_of_work import TransactionConnection


class BaseRepository:
    """Hold the connection a request’s adapters share.

    Subclasses call the protected helpers. They do not open a connection,
    and they do not grow ``add`` or ``delete`` as public methods: an audit
    adapter that could delete would undo the Article 12 grant.
    """

    def __init__(self, connection: TransactionConnection) -> None:
        self._connection = connection

    async def _execute(
        self,
        statement: str,
        parameters: Mapping[str, object] | None = None,
    ) -> None:
        """Run one statement on the enlisted connection."""
        await self._connection.execute(statement, parameters)

    async def _fetch_one(
        self,
        statement: str,
        parameters: Mapping[str, object],
    ) -> tuple[object, ...] | None:
        """Return one row, or ``None`` when the statement matches nothing."""
        return await self._connection.fetch_one(statement, parameters)

    async def _fetch_all(
        self,
        statement: str,
        parameters: Mapping[str, object],
    ) -> tuple[tuple[object, ...], ...]:
        """Return every row the statement matches, in the statement’s order."""
        return await self._connection.fetch_all(statement, parameters)
