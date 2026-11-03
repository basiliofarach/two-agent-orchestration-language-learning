"""Create the campaign database before Alembic migrates it."""

import re
import sys
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
        return urlunsplit((parts.scheme, parts.netloc, f"/{name}", "", ""))


class SimulationDatabase:
    """``tutor_sim`` on the server the owner settings already name."""

    EXTENSION = "CREATE EXTENSION IF NOT EXISTS vector"

    def __init__(self, name: str = "tutor_sim") -> None:
        self._name = DatabaseIdentifier(name)

    def create_statement(self, exists: bool) -> str | None:
        """``None`` when the database is already there."""
        if exists:
            return None
        return f"CREATE DATABASE {self._name.quoted()}"

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


def main() -> int:
    """Print the owner URL of the campaign database. Alembic reads that URL."""
    settings = ApplicationSettings()
    url = SimulationDatabase().ensure(MigrationDatabaseUrl(settings).value())
    sys.stdout.write(url + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
