"""The application role can read the request path and cannot write it."""

import psycopg
import pytest
from psycopg import sql
from tests.support.migrated_database import MigratedDatabase

from tutor_api.settings import ApplicationSettings


class ApplicationSession:
    """Statements run as the role the migration granted, not the owner."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._role = ApplicationSettings().postgres_app_user

    def selects(self) -> None:
        """SELECT on each request-path table succeeds."""
        with psycopg.connect(self._url) as connection:
            self._assume(connection)
            connection.execute("SELECT count(*) FROM policy_version")
            connection.execute("SELECT count(*) FROM kb_document")
            connection.execute("SELECT count(*) FROM kb_chunk")

    def insert_is_denied(self) -> None:
        """INSERT on a request-path table is rejected for this role."""
        with psycopg.connect(self._url) as connection:
            self._assume(connection)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(
                    """
                    INSERT INTO kb_document (
                        id, source_uri, version, review_status
                    ) VALUES (
                        '00000000-0000-4000-8000-000000000099',
                        'kb://denied', '1', 'pending'
                    )
                    """
                )

    def _assume(self, connection: psycopg.Connection) -> None:
        connection.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(self._role)))


class TestRequestPathPrivileges:
    def test_the_application_role_can_read_and_cannot_write(
        self, fresh_database: str
    ) -> None:
        MigratedDatabase().upgrade(fresh_database)
        session = ApplicationSession(fresh_database)
        session.selects()
        session.insert_is_denied()
