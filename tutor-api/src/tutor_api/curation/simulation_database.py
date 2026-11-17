"""Create, or recreate, the campaign database before Alembic migrates it.

``--reset`` drops ``tutor_sim`` first, so a seed never mixes with an older
one. Audit records are evidence: a reset that would drop them stops unless
the operator also passes ``--discard-audit``.
"""

import re
import sys
from typing import TextIO
from urllib.parse import urlsplit, urlunsplit

import psycopg

from tutor_api.adapters.persistence.database_url import DriverSwap, MigrationDatabaseUrl
from tutor_api.settings import ApplicationSettings


class DatabaseIdentifier:
    """A database name that can be quoted into ``CREATE DATABASE``."""

    _GRAMMAR = re.compile(r"\A[a-z_][a-z0-9_]{0,62}\Z")

    def __init__(self, name: str) -> None:
        if self._GRAMMAR.fullmatch(name) is None:
            msg = "database name is not a usable identifier"
            raise ValueError(msg)
        self._name = name

    def value(self) -> str:
        """The name, unquoted."""
        return self._name

    def quoted(self) -> str:
        """The name as a quoted identifier."""
        return f'"{self._name}"'


class DatabaseUrl:
    """Point an owner URL at another database on the same server."""

    def plain(self, owner_url: str) -> str:
        """The URL psycopg can open. The SQLAlchemy driver prefix is removed."""
        return DriverSwap("postgresql").apply(owner_url)

    def renamed(self, url: str, name: str) -> str:
        """The same server and credentials, with ``name`` as the database."""
        parts = urlsplit(url)
        return urlunsplit(
            (parts.scheme, parts.netloc, f"/{name}", parts.query, parts.fragment)
        )


class AuditRecordsPresent(RuntimeError):
    """The database to drop holds audit records and the operator did not agree."""


class ResetRefused(ValueError):
    """The reset would drop the database the owner URL names."""


class SimulationDatabase:
    """``tutor_sim`` on the server the owner settings already name."""

    EXTENSION = "CREATE EXTENSION IF NOT EXISTS vector"
    AUDIT_TABLE = "turn_audit"

    def __init__(self, name: str = "tutor_sim") -> None:
        self._name = DatabaseIdentifier(name)

    def create_statement(self, exists: bool) -> str | None:
        """``None`` when the database is already there."""
        if exists:
            return None
        return f"CREATE DATABASE {self._name.quoted()}"

    def drop_statement(self) -> str:
        """Drop even with open connections: a stale API must not keep old data."""
        return f"DROP DATABASE IF EXISTS {self._name.quoted()} WITH (FORCE)"

    def reset(self, owner_url: str, discard_audit: bool) -> str:
        """Drop the database, then create it empty. Return its owner URL."""
        urls = DatabaseUrl()
        plain = urls.plain(owner_url)
        if urlsplit(plain).path.lstrip("/") == self._name.value():
            msg = f"refusing to reset {self._name.value()}: the owner URL names it"
            raise ResetRefused(msg)
        with psycopg.connect(plain, autocommit=True) as connection:
            exists = connection.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (self._name.value(),),
            ).fetchone()
        if exists is not None:
            records = self._audit_records(urls.renamed(plain, self._name.value()))
            if records and not discard_audit:
                msg = (
                    f"{self._name.value()} holds {records} audit records from "
                    "simulation runs; pass --discard-audit to drop them"
                )
                raise AuditRecordsPresent(msg)
            with psycopg.connect(plain, autocommit=True) as connection:
                connection.execute(self.drop_statement())
        return self.ensure(owner_url)

    def _audit_records(self, url: str) -> int:
        with psycopg.connect(url, autocommit=True) as connection:
            table = connection.execute(
                "SELECT to_regclass(%s)", (self.AUDIT_TABLE,)
            ).fetchone()
            if table is None or table[0] is None:
                return 0
            row = connection.execute(
                f"SELECT count(*) FROM {self.AUDIT_TABLE}"  # noqa: S608 - constant
            ).fetchone()
        return 0 if row is None else int(row[0])

    def ensure(self, owner_url: str) -> str:
        """Create the database and the vector extension. Return its owner URL."""
        urls = DatabaseUrl()
        plain = urls.plain(owner_url)
        with psycopg.connect(plain, autocommit=True) as connection:
            row = connection.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (self._name.value(),),
            ).fetchone()
            statement = self.create_statement(row is not None)
            if statement is not None:
                connection.execute(statement)
        created = urls.renamed(plain, self._name.value())
        with psycopg.connect(created, autocommit=True) as connection:
            connection.execute(self.EXTENSION)
        return urls.renamed(owner_url, self._name.value())


class SimulationDatabaseMain:
    """The process entry: print the campaign database's owner URL.

    Alembic reads that URL. Settings and the output stream are injected so the
    entry runs under test against a throwaway server.
    """

    _FLAGS = frozenset({"--reset", "--discard-audit"})

    def __init__(
        self,
        settings: ApplicationSettings,
        output: TextIO,
        database: SimulationDatabase,
        errors: TextIO | None = None,
    ) -> None:
        self._settings = settings
        self._output = output
        self._database = database
        self._errors = sys.stderr if errors is None else errors

    def run(self, argv: tuple[str, ...] = ()) -> int:
        """Ensure, or reset, the database; write its URL; return a status."""
        unknown = set(argv) - self._FLAGS
        if unknown:
            self._errors.write(
                "usage: simulation_database [--reset [--discard-audit]]\n"
            )
            return 2
        owner = MigrationDatabaseUrl(self._settings).value()
        try:
            if "--reset" in argv:
                url = self._database.reset(owner, "--discard-audit" in argv)
            else:
                url = self._database.ensure(owner)
        except (AuditRecordsPresent, ResetRefused) as exc:
            self._errors.write(f"simulation_database: {exc}\n")
            return 1
        self._output.write(url + "\n")
        return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(
        SimulationDatabaseMain(
            ApplicationSettings(), sys.stdout, SimulationDatabase()
        ).run(tuple(sys.argv[1:]))
    )
