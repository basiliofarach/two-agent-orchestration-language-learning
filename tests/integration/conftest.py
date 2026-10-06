"""One Postgres container for the whole suite; one fresh database per test.

Starting a container costs about 1.6s and the suite did it 24 times — roughly
40 of its 48 seconds. Isolation never needed a new *container*, only a new
*database*, and `CREATE DATABASE` inside a running server costs milliseconds.

The isolation is the same: every DEC-0012 object the tests assert on is
database-scoped. The `ciphertext` domain, the `protected_column_exemption`
table, the event trigger and the audit triggers all live in one database, so a
test that installs them cannot be seen by the next.
"""

import os
from collections.abc import Iterator
from uuid import uuid4

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer
from tests.support.runtime_pin import RuntimePin


class ContainerUrl:
    """Plain psycopg URLs derived from the running container."""

    _DRIVERS = (
        "postgresql+psycopg2://",
        "postgresql+psycopg://",
        "postgresql+asyncpg://",
    )

    def __init__(self, container: PostgresContainer) -> None:
        self._raw = container.get_connection_url()

    def plain(self) -> str:
        """The maintenance URL, on the container's default database."""
        for prefix in self._DRIVERS:
            if self._raw.startswith(prefix):
                return "postgresql://" + self._raw[len(prefix) :]
        return self._raw

    def named(self, database: str) -> str:
        """The same server, pointed at ``database``."""
        return PlainUrl(self.plain()).named(database)


class PlainUrl:
    """A maintenance URL whose database name can be replaced."""

    def __init__(self, raw: str) -> None:
        self._raw = raw

    def plain(self) -> str:
        """The maintenance URL this object was built from."""
        return self._raw

    def named(self, database: str) -> str:
        """The same server, pointed at ``database``."""
        base, _, _ = self._raw.rpartition("/")
        return f"{base}/{database}"


@pytest.fixture(scope="session")
def postgres_maintenance_url() -> Iterator[str]:
    """The sandbox server when the runner set one, otherwise a container.

    ``TUTOR_SANDBOX_URL`` is the throwaway compose project from
    ``make sandbox-test``. It is not the database ``make up`` serves, and
    this process does not start a second container beside it.
    """
    sandbox = os.environ.get("TUTOR_SANDBOX_URL")
    if sandbox:
        yield sandbox
        return
    os.environ["TESTCONTAINERS_RYUK_DISABLED"] = "true"
    with PostgresContainer(image=RuntimePin().postgres_image()) as container:
        yield ContainerUrl(container).plain()


@pytest.fixture
def fresh_database(postgres_maintenance_url: str) -> Iterator[str]:
    """A database of this test's own, dropped when it finishes."""
    url = PlainUrl(postgres_maintenance_url)
    name = f"t_{uuid4().hex}"
    with psycopg.connect(url.plain(), autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    try:
        yield url.named(name)
    finally:
        # FORCE so a connection the test left open cannot block the drop and
        # leak the database into the next run.
        with psycopg.connect(url.plain(), autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
