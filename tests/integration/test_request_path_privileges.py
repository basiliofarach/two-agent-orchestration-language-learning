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
            connection.execute(
                "SELECT learner_id, retain_until, proficiency_level FROM learner"
            )
            connection.execute(
                "SELECT learner_id, item_id, correct, occurred_at "
                "FROM learner_history_event ORDER BY occurred_at, id"
            )
            connection.execute(
                "SELECT id, learner_id, stopped_at FROM tutoring_session"
            )

    def pseudonym_is_denied(self) -> None:
        """The grant is column-level: the pseudonym is not readable at all."""
        with psycopg.connect(self._url) as connection:
            self._assume(connection)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute("SELECT pseudonym FROM learner")
            connection.rollback()
            self._assume(connection)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute("SELECT * FROM learner")

    def session_secrets_are_denied(self) -> None:
        """The session check cannot read the tutor or the stop reason."""
        with psycopg.connect(self._url) as connection:
            self._assume(connection)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute("SELECT tutor_id FROM tutoring_session")
            connection.rollback()
            self._assume(connection)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute("SELECT stop_reason FROM tutoring_session")
            connection.rollback()
            self._assume(connection)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute("SELECT * FROM tutoring_session")

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
            connection.rollback()
            self._assume(connection)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(
                    """
                    INSERT INTO learner (
                        learner_id, pseudonym, proficiency_level, retain_until
                    ) VALUES (
                        '00000000-0000-4000-8000-000000000098',
                        '\\x01', '\\x01', '2026-12-01T00:00:00Z'
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

    def test_the_application_role_cannot_read_the_learner_pseudonym(
        self, fresh_database: str
    ) -> None:
        MigratedDatabase().upgrade(fresh_database)
        session = ApplicationSession(fresh_database)
        session.pseudonym_is_denied()
        session.session_secrets_are_denied()
