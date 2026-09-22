"""A plaintext column on a stored table fails in the database (DEC-0012)."""

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

    def test_install_uses_the_callers_transaction(self) -> None:
        schema = EncryptionAtRestSchema()
        with (
            PostgresContainer(image=RuntimePin().postgres_image()) as postgres,
            psycopg.connect(PostgresUrl().from_container(postgres)) as connection,
        ):
            schema.install(connection)
            connection.rollback()
            with connection.cursor() as cursor:
                cursor.execute("SELECT to_regtype('public.ciphertext')")
                installed_type = cursor.fetchone()[0]
        assert installed_type is None

    def test_plaintext_is_rejected_and_ciphertext_round_trips(self) -> None:
        schema = EncryptionAtRestSchema()
        cipher = AesGcmEnvelope(key=bytes(range(32)), key_id=UUID(int=1))
        with (
            PostgresContainer(image=RuntimePin().postgres_image()) as postgres,
            psycopg.connect(PostgresUrl().from_container(postgres)) as connection,
        ):
            schema.install(connection)
            connection.commit()
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
            connection.commit()
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
            connection.commit()
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT table_name, column_name
                    FROM protected_column_exemption
                    ORDER BY table_name, column_name
                    """
                )
                rows = set(cursor.fetchall())
        assert rows == {
            ("alembic_version", "version_num"),
            ("kb_chunk", "embedding"),
            ("kb_document", "review_status"),
            ("kb_document", "source_uri"),
            ("kb_document", "version"),
            ("learner", "learner_id"),
            ("learner_history", "learner_id"),
            ("learner_history_event", "learner_id"),
            ("protected_column_exemption", "column_name"),
            ("protected_column_exemption", "decision_ref"),
            ("protected_column_exemption", "reason"),
            ("protected_column_exemption", "schema_name"),
            ("protected_column_exemption", "table_name"),
            ("gate_evaluation", "decision"),
            ("gate_evaluation", "gate_name"),
            ("gate_evaluation", "policy_rule_id"),
            ("policy_version", "version"),
            ("turn_audit", "model_revision"),
            ("turn_audit", "policy_version"),
            ("turn_audit", "previous_record_hash"),
            ("turn_audit", "record_hash"),
            ("turn_audit", "recorded_at"),
            ("turn_audit", "turn_id"),
        }

    def test_audit_reports_plaintext_created_before_the_guard(self) -> None:
        schema = EncryptionAtRestSchema()
        with (
            PostgresContainer(image=RuntimePin().postgres_image()) as postgres,
            psycopg.connect(PostgresUrl().from_container(postgres)) as connection,
        ):
            with connection.cursor() as cursor:
                cursor.execute("CREATE TABLE legacy_note (body text)")
            schema.install(connection)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT relation.relname, attribute.attname
                      FROM pg_attribute attribute
                      JOIN pg_class relation
                        ON relation.oid = attribute.attrelid
                      JOIN pg_namespace namespace
                        ON namespace.oid = relation.relnamespace
                      JOIN pg_type column_type
                        ON column_type.oid = attribute.atttypid
                      LEFT JOIN protected_column_exemption exemption
                        ON exemption.table_name = relation.relname
                       AND exemption.column_name = attribute.attname
                     WHERE namespace.nspname = 'public'
                       AND relation.relkind = 'r'
                       AND attribute.attnum > 0
                       AND NOT attribute.attisdropped
                       AND column_type.typname IN (
                           'text', 'varchar', 'bpchar', 'json', 'jsonb', 'bytea'
                       )
                       AND exemption.column_name IS NULL
                    """
                )
                found = tuple(cursor.fetchall())
        assert found == (("legacy_note", "body"),)

    def test_new_table_is_ciphertext_or_an_exemption(self) -> None:
        schema = EncryptionAtRestSchema()
        with (
            PostgresContainer(image=RuntimePin().postgres_image()) as postgres,
            psycopg.connect(PostgresUrl().from_container(postgres)) as connection,
        ):
            schema.install(connection)
            connection.commit()
            with (
                connection.cursor() as cursor,
                pytest.raises(psycopg.Error, match="DEC-0012"),
            ):
                cursor.execute("CREATE TABLE scratch_pad (body text)")
            connection.rollback()
            with connection.cursor() as cursor:
                cursor.execute("CREATE TABLE session_note (body ciphertext)")
            with (
                connection.cursor() as cursor,
                pytest.raises(psycopg.Error, match="DEC-0012"),
            ):
                cursor.execute("CREATE TABLE other_note (body text)")

    def test_domain_and_array_cannot_disguise_plaintext(self) -> None:
        schema = EncryptionAtRestSchema()
        with (
            PostgresContainer(image=RuntimePin().postgres_image()) as postgres,
            psycopg.connect(PostgresUrl().from_container(postgres)) as connection,
        ):
            schema.install(connection)
            connection.commit()
            with (
                connection.cursor() as cursor,
                pytest.raises(psycopg.Error, match="DEC-0012"),
            ):
                cursor.execute(
                    "CREATE DOMAIN disguised_text AS text; "
                    "CREATE TABLE disguised_note (body disguised_text)"
                )
            connection.rollback()
            with (
                connection.cursor() as cursor,
                pytest.raises(psycopg.Error, match="DEC-0012"),
            ):
                cursor.execute("CREATE TABLE note_list (items text[])")

    def test_a_table_in_another_schema_cannot_hold_plaintext(self) -> None:
        schema = EncryptionAtRestSchema()
        with (
            PostgresContainer(image=RuntimePin().postgres_image()) as postgres,
            psycopg.connect(PostgresUrl().from_container(postgres)) as connection,
        ):
            schema.install(connection)
            connection.commit()
            with (
                connection.cursor() as cursor,
                pytest.raises(psycopg.Error, match="DEC-0012"),
            ):
                cursor.execute(
                    "CREATE SCHEMA staging; CREATE TABLE staging.note (body text)"
                )
            connection.rollback()
            with connection.cursor() as cursor:
                cursor.execute(
                    "CREATE SCHEMA staging; CREATE TABLE staging.note (body ciphertext)"
                )
            connection.rollback()

    def test_a_public_exemption_does_not_exempt_another_schema(self) -> None:
        schema = EncryptionAtRestSchema()
        with (
            PostgresContainer(image=RuntimePin().postgres_image()) as postgres,
            psycopg.connect(PostgresUrl().from_container(postgres)) as connection,
        ):
            schema.install(connection)
            connection.commit()
            with (
                connection.cursor() as cursor,
                pytest.raises(psycopg.Error, match="DEC-0012"),
            ):
                cursor.execute(
                    "CREATE SCHEMA shadow; "
                    "CREATE TABLE shadow.turn_audit (record_hash text)"
                )
            connection.rollback()

    def test_a_lookalike_ciphertext_domain_cannot_shadow_the_real_one(self) -> None:
        schema = EncryptionAtRestSchema()
        with (
            PostgresContainer(image=RuntimePin().postgres_image()) as postgres,
            psycopg.connect(PostgresUrl().from_container(postgres)) as connection,
        ):
            schema.install(connection)
            connection.commit()
            with (
                connection.cursor() as cursor,
                pytest.raises(psycopg.Error, match="DEC-0012"),
            ):
                cursor.execute(
                    "CREATE SCHEMA impostor; "
                    "CREATE DOMAIN impostor.ciphertext AS text; "
                    "CREATE TABLE impostor.note (body impostor.ciphertext)"
                )
            connection.rollback()

    def test_create_table_as_is_rejected_when_it_creates_the_column(self) -> None:
        schema = EncryptionAtRestSchema()
        with (
            PostgresContainer(image=RuntimePin().postgres_image()) as postgres,
            psycopg.connect(PostgresUrl().from_container(postgres)) as connection,
        ):
            schema.install(connection)
            connection.commit()
            with (
                connection.cursor() as cursor,
                pytest.raises(psycopg.Error, match="DEC-0012"),
            ):
                cursor.execute(
                    "CREATE TABLE ctas_note AS SELECT 'Oak Street'::text AS body"
                )
            connection.rollback()
            with connection.cursor() as cursor:
                cursor.execute("SELECT to_regclass('public.ctas_note')")
                assert cursor.fetchone()[0] is None

    def test_select_into_is_rejected_when_it_creates_the_column(self) -> None:
        schema = EncryptionAtRestSchema()
        with (
            PostgresContainer(image=RuntimePin().postgres_image()) as postgres,
            psycopg.connect(PostgresUrl().from_container(postgres)) as connection,
        ):
            schema.install(connection)
            connection.commit()
            with (
                connection.cursor() as cursor,
                pytest.raises(psycopg.Error, match="DEC-0012"),
            ):
                cursor.execute("SELECT 'Oak Street'::text AS body INTO into_note")
            connection.rollback()
            with connection.cursor() as cursor:
                cursor.execute("SELECT to_regclass('public.into_note')")
                assert cursor.fetchone()[0] is None
