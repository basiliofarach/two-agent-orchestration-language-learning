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
        base, _, _ = self.plain().rpartition("/")
        return f"{base}/{database}"


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[PostgresContainer]:
    """The one server every database-backed test shares."""
    os.environ["TESTCONTAINERS_RYUK_DISABLED"] = "true"
    with PostgresContainer(image=RuntimePin().postgres_image()) as container:
        yield container


@pytest.fixture
def fresh_database(postgres_container: PostgresContainer) -> Iterator[str]:
    """A database of this test's own, dropped when it finishes."""
    url = ContainerUrl(postgres_container)
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
