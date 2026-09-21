"""A plaintext column on a protected table fails in the database (DEC-0012)."""

import os
from uuid import UUID

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer
from tests.support.runtime_pin import RuntimePin

from tutor_api.adapters.persistence.aes_gcm_envelope import AesGcmEnvelope
from tutor_api.adapters.persistence.encryption_at_rest import EncryptionAtRestSchema


class PostgresUrl:
    def from_container(self, postgres: PostgresContainer) -> str:
        raw = postgres.get_connection_url()
        return raw.replace("postgresql+psycopg2://", "postgresql://").replace(
            "postgresql+psycopg://",
            "postgresql://",
        )


class TestEncryptionAtRestSchema:
    def setup_method(self) -> None:
        os.environ["TESTCONTAINERS_RYUK_DISABLED"] = "true"

    def test_plaintext_is_rejected_and_ciphertext_round_trips(self) -> None:
        schema = EncryptionAtRestSchema()
        cipher = AesGcmEnvelope(key=bytes(range(32)), key_id=UUID(int=1))
        with (
            PostgresContainer(image=RuntimePin().postgres_image()) as postgres,
            psycopg.connect(PostgresUrl().from_container(postgres)) as connection,
        ):
            schema.install(connection)
            with (
                connection.cursor() as cursor,
                pytest.raises(psycopg.Error, match="DEC-0012"),
            ):
                cursor.execute("CREATE TABLE turn_audit (learner_prompt_redacted text)")
            connection.rollback()
            with (
                connection.cursor() as cursor,
                pytest.raises(psycopg.Error, match="DEC-0012"),
            ):
                cursor.execute("CREATE TABLE learner (proficiency_level varchar(16))")
            connection.rollback()
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE turn_audit (
                        turn_id uuid,
                        record_hash text,
                        learner_prompt_redacted ciphertext
                    )
                    """
                )
                envelope = cipher.encrypt(b"Where is the library?")
                cursor.execute(
                    """
                    INSERT INTO turn_audit (learner_prompt_redacted)
                    VALUES (%s)
                    """,
                    (envelope,),
                )
                cursor.execute("SELECT learner_prompt_redacted FROM turn_audit")
                stored = bytes(cursor.fetchone()[0])
            with connection.cursor() as cursor, pytest.raises(psycopg.Error):
                cursor.execute(
                    """
                    INSERT INTO turn_audit (learner_prompt_redacted)
                    VALUES (%s)
                    """,
                    (b"Where is the library?",),
                )
            connection.rollback()
        assert b"Where is the library?" not in stored
        assert cipher.decrypt(stored) == b"Where is the library?"

    def test_alter_plaintext_fails_until_an_exemption_is_registered(self) -> None:
        schema = EncryptionAtRestSchema()
        with (
            PostgresContainer(image=RuntimePin().postgres_image()) as postgres,
            psycopg.connect(PostgresUrl().from_container(postgres)) as connection,
        ):
            schema.install(connection)
            with connection.cursor() as cursor:
                cursor.execute("CREATE TABLE gate_evaluation (reason ciphertext)")
            with (
                connection.cursor() as cursor,
                pytest.raises(psycopg.Error, match="DEC-0012"),
            ):
                cursor.execute("ALTER TABLE gate_evaluation ADD COLUMN note text")
            connection.rollback()
            with connection.cursor() as cursor:
                cursor.execute("CREATE TABLE gate_evaluation (reason ciphertext)")
                cursor.execute(
                    """
                    INSERT INTO protected_column_exemption (
                        table_name, column_name, reason, decision_ref
                    ) VALUES ('gate_evaluation', 'note', 'fixture reason', 'DEC-0012')
                    """
                )
                cursor.execute("ALTER TABLE gate_evaluation ADD COLUMN note text")
            with connection.cursor() as cursor, pytest.raises(psycopg.Error):
                cursor.execute(
                    """
                    INSERT INTO protected_column_exemption (
                        table_name, column_name, reason, decision_ref
                    ) VALUES ('gate_evaluation', 'empty', '   ', 'DEC-0012')
                    """
                )
            connection.rollback()

    def test_seeded_exemptions_are_readable(self) -> None:
        schema = EncryptionAtRestSchema()
        with (
            PostgresContainer(image=RuntimePin().postgres_image()) as postgres,
            psycopg.connect(PostgresUrl().from_container(postgres)) as connection,
        ):
            schema.install(connection)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT table_name, column_name
                    FROM protected_column_exemption
                    ORDER BY table_name, column_name
                    """
                )
                rows = set(cursor.fetchall())
        expected = {(row.table_name, row.column_name) for row in schema.exemptions()}
        assert rows == expected
