"""The base every persistence adapter extends.

The first project's repository base adds, loads and deletes ORM rows. This
store is SQLAlchemy Core on one request connection (DEC-0014), so the shared
base is the three statement helpers and the row decoders every adapter was
writing for itself — and nothing that would become a second public API. A
concrete adapter's public methods stay exactly its port's methods
(DEC-0011); everything here is protected.

What the base does not have is as deliberate as what it has. There is no
``add``, ``update`` or ``delete``: an audit adapter that inherited a delete
would undo the Article 12 grant, and an adapter that inherited an update
would bypass the security-definer functions that own session state. Each
adapter writes its own statements, and the database grant decides whether
they run.
"""

from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

from tutor_core.domain.ports.unit_of_work import TransactionConnection


class RowReader:
    """Decode the column types every adapter reads back.

    Separate from ``BaseRepository`` so a class that only decodes rows —
    ``AuditRecordDecoder`` — inherits the decoders without holding a
    connection it would never use.
    """

    def _uuid(self, value: object) -> UUID:
        """A ``uuid`` column. The driver returns ``UUID``; text is accepted."""
        if isinstance(value, UUID):
            return value
        if isinstance(value, str):
            return UUID(value)
        msg = "column is not an identifier"
        raise ValueError(msg)

    def _instant(self, value: object) -> datetime:
        """A ``timestamptz`` column. A naive value is refused (DEC-0010).

        ``timestamp`` without time zone comes back naive from psycopg. The
        schema forbids that type; this is the read-side backstop.
        """
        if isinstance(value, datetime) and value.utcoffset() is not None:
            return value
        msg = "instant column is not a timestamp, or is not timezone-aware"
        raise ValueError(msg)

    def _optional_instant(self, value: object) -> datetime | None:
        """A nullable ``timestamptz`` column: unset until its event happens."""
        if value is None:
            return None
        return self._instant(value)

    def _ciphertext(self, value: object) -> bytes:
        """A ``ciphertext`` column. The driver returns bytes or a memory view."""
        if isinstance(value, bytes):
            return value
        if isinstance(value, bytearray | memoryview):
            return bytes(value)
        msg = "ciphertext column is not bytes"
        raise ValueError(msg)


class BaseRepository(RowReader):
    """Hold the connection a request's adapters share, and decode its rows.

    Subclasses call the protected helpers. They never open a connection: the
    one they are given is the request's, enlisted in its unit of work, so a
    read sees the writes of the same request and a write commits with them.
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
        parameters: Mapping[str, object] | None = None,
    ) -> tuple[object, ...] | None:
        """Return one row, or ``None`` when the statement matches nothing."""
        return await self._connection.fetch_one(statement, parameters or {})

    async def _fetch_all(
        self,
        statement: str,
        parameters: Mapping[str, object] | None = None,
    ) -> tuple[tuple[object, ...], ...]:
        """Return every row the statement matches, in the statement's order."""
        return await self._connection.fetch_all(statement, parameters or {})

    def _raised_sqlstate(self, error: BaseException, sqlstate: str) -> bool:
        """Whether ``error``, or the driver error inside it, carries ``sqlstate``.

        A trigger or security-definer function refuses with its own SQLSTATE.
        The driver error carries ``sqlstate``; SQLAlchemy wraps it as
        ``orig``. Async and sync drivers name the attribute the same.
        """
        for candidate in (error, getattr(error, "orig", None), error.__cause__):
            if getattr(candidate, "sqlstate", None) == sqlstate:
                return True
        return False
