"""BE-05 and BE-06 schema, applied by Alembic to a fresh database."""

import os
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from testcontainers.postgres import PostgresContainer
from tests.support.runtime_pin import RuntimePin

from tutor_api.adapters.persistence.database import DatabaseEngine
from tutor_api.adapters.persistence.schema import ApplicationRole
from tutor_api.adapters.persistence.unit_of_work import (
    SqlAlchemyUnitOfWork,
    TransactionConnection,
)
from tutor_api.settings import DatabaseSettings
from tutor_core.domain.ports.unit_of_work import TransactionalWork

_ROLE_NAME = DatabaseSettings().postgres_app_user


class PostgresUrl:
    def sync(self, postgres: PostgresContainer) -> str:
        raw = postgres.get_connection_url()
        for prefix in (
            "postgresql+psycopg2://",
            "postgresql+psycopg://",
            "postgresql+asyncpg://",
            "postgresql://",
        ):
            if raw.startswith(prefix):
                return "postgresql+psycopg://" + raw[len(prefix) :]
        return raw

    def async_url(self, postgres: PostgresContainer) -> str:
        return self.sync(postgres).replace(
            "postgresql+psycopg://",
            "postgresql+asyncpg://",
            1,
        )

    def plain(self, postgres: PostgresContainer) -> str:
        return self.sync(postgres).replace("postgresql+psycopg://", "postgresql://", 1)


class AlembicRunner:
    def __init__(self, url: str) -> None:
        root = Path(__file__).resolve().parents[2] / "tutor-api"
        self._config = Config(str(root / "alembic.ini"))
        self._config.set_main_option("script_location", str(root / "alembic"))
        self._config.set_main_option("sqlalchemy.url", url)

    def upgrade(self) -> None:
        command.upgrade(self._config, "head")

    def downgrade(self) -> None:
        command.downgrade(self._config, "base")


class OneWrite(TransactionalWork):
    def __init__(self, connection: TransactionConnection) -> None:
        self._connection = connection

    async def run(self) -> None:
        await self._connection.execute("INSERT INTO uow_probe (id) VALUES (7)")


class ConflictingWrites(TransactionalWork):
    def __init__(self, connection: TransactionConnection) -> None:
        self._connection = connection

    async def run(self) -> None:
        await self._connection.execute("INSERT INTO uow_probe (id) VALUES (1)")
        await self._connection.execute("INSERT INTO uow_probe (id) VALUES (1)")


class TestPersistenceSchema:
    def setup_method(self) -> None:
        os.environ["TESTCONTAINERS_RYUK_DISABLED"] = "true"

    def test_migrate_forward_back_and_forward(self) -> None:
        with (
            PostgresContainer(image=RuntimePin().postgres_image()) as postgres,
            psycopg.connect(PostgresUrl().plain(postgres)) as connection,
        ):
            runner = AlembicRunner(PostgresUrl().sync(postgres))
            runner.upgrade()
            assert self._tables(connection) >= {"learner", "turn_audit"}
            runner.downgrade()
            assert "learner" not in self._tables(connection)
            assert "turn_audit" not in self._tables(connection)
            runner.upgrade()
            assert self._tables(connection) >= {"learner", "turn_audit", "kb_chunk"}

    def test_mismatched_embedding_dimension_raises(self) -> None:
        with (
            PostgresContainer(image=RuntimePin().postgres_image()) as postgres,
            psycopg.connect(PostgresUrl().plain(postgres)) as connection,
        ):
            AlembicRunner(PostgresUrl().sync(postgres)).upgrade()
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO kb_document (id, source_uri, version, review_status)
                    VALUES (
                        '00000000-0000-4000-8000-000000000001',
                        'kb://library',
                        '1',
                        'approved'
                    )
                    """
                )
                with pytest.raises(psycopg.Error):
                    cursor.execute(
                        """
                        INSERT INTO kb_chunk (
                            id, document_id, ordinal, content, embedding
                        ) VALUES (
                            '00000000-0000-4000-8000-000000000002',
                            '00000000-0000-4000-8000-000000000001',
                            0,
                            %s,
                            '[1,2]'
                        )
                        """,
                        (self._envelope(),),
                    )

    def test_learner_without_retain_until_raises(self) -> None:
        with (
            PostgresContainer(image=RuntimePin().postgres_image()) as postgres,
            psycopg.connect(PostgresUrl().plain(postgres)) as connection,
        ):
            AlembicRunner(PostgresUrl().sync(postgres)).upgrade()
            with connection.cursor() as cursor, pytest.raises(psycopg.Error):
                cursor.execute(
                    """
                    INSERT INTO learner (learner_id, pseudonym, proficiency_level)
                    VALUES (
                        '00000000-0000-4000-8000-000000000003',
                        %s,
                        %s
                    )
                    """,
                    (self._envelope(), self._envelope()),
                )

    def test_session_requires_an_existing_learner(self) -> None:
        with (
            PostgresContainer(image=RuntimePin().postgres_image()) as postgres,
            psycopg.connect(PostgresUrl().plain(postgres)) as connection,
        ):
            AlembicRunner(PostgresUrl().sync(postgres)).upgrade()
            with connection.cursor() as cursor, pytest.raises(psycopg.Error):
                cursor.execute(
                    """
                    INSERT INTO tutoring_session (
                        id, tutor_id, learner_id, started_at
                    ) VALUES (
                        '00000000-0000-4000-8000-000000000004',
                        %s,
                        '00000000-0000-4000-8000-000000000099',
                        '2026-01-01T00:00:00Z'
                    )
                    """,
                    (self._envelope(),),
                )

    async def test_two_writes_roll_back_together(self) -> None:
        with PostgresContainer(image=RuntimePin().postgres_image()) as postgres:
            AlembicRunner(PostgresUrl().sync(postgres)).upgrade()
            with psycopg.connect(PostgresUrl().plain(postgres)) as connection:
                connection.execute("CREATE TABLE uow_probe (id integer PRIMARY KEY)")
                connection.commit()
            engine = DatabaseEngine(PostgresUrl().async_url(postgres))
            try:
                committed = await engine.connect()
                await SqlAlchemyUnitOfWork(committed).run(OneWrite(committed))
                enlisted = await engine.connect()
                with pytest.raises(Exception, match="unique"):
                    await SqlAlchemyUnitOfWork(enlisted).run(
                        ConflictingWrites(enlisted)
                    )
                with psycopg.connect(PostgresUrl().plain(postgres)) as connection:
                    count = connection.execute("SELECT count(*) FROM uow_probe")
                    row = count.fetchone()
                assert row is not None
                assert row[0] == 1
            finally:
                await engine.dispose()

    def test_update_against_turn_audit_raises_at_database_level(self) -> None:
        self._assert_owner_mutation_raises("UPDATE turn_audit SET refused = true")

    def test_delete_against_turn_audit_raises_at_database_level(self) -> None:
        self._assert_owner_mutation_raises("DELETE FROM turn_audit")

    def test_update_against_gate_evaluation_raises_at_database_level(self) -> None:
        self._assert_owner_mutation_raises(
            "UPDATE gate_evaluation SET decision = 'stop'"
        )

    def test_delete_against_gate_evaluation_raises_at_database_level(self) -> None:
        self._assert_owner_mutation_raises("DELETE FROM gate_evaluation")

    def test_application_role_has_no_update_or_delete_grant(self) -> None:
        with (
            PostgresContainer(image=RuntimePin().postgres_image()) as postgres,
            psycopg.connect(PostgresUrl().plain(postgres)) as connection,
        ):
            AlembicRunner(PostgresUrl().sync(postgres)).upgrade()
            self._insert_audit_row(connection)
            connection.commit()
            with connection.cursor() as cursor, pytest.raises(psycopg.Error):
                cursor.execute(f"SET ROLE {ApplicationRole(_ROLE_NAME).identifier()}")
                cursor.execute("UPDATE turn_audit SET refused = true")

    def test_truncate_of_audit_table_is_refused_for_application_role(self) -> None:
        with (
            PostgresContainer(image=RuntimePin().postgres_image()) as postgres,
            psycopg.connect(PostgresUrl().plain(postgres)) as connection,
        ):
            AlembicRunner(PostgresUrl().sync(postgres)).upgrade()
            with connection.cursor() as cursor, pytest.raises(psycopg.Error):
                cursor.execute(f"SET ROLE {ApplicationRole(_ROLE_NAME).identifier()}")
                cursor.execute("TRUNCATE turn_audit")

    def test_gate_evaluation_rejects_unknown_decision(self) -> None:
        with (
            PostgresContainer(image=RuntimePin().postgres_image()) as postgres,
            psycopg.connect(PostgresUrl().plain(postgres)) as connection,
        ):
            AlembicRunner(PostgresUrl().sync(postgres)).upgrade()
            self._insert_audit_row(connection)
            with connection.cursor() as cursor, pytest.raises(psycopg.Error):
                cursor.execute(
                    """
                    INSERT INTO gate_evaluation (
                        id, turn_id, gate_name, decision, reason,
                        policy_rule_id, evaluated_at
                    ) VALUES (
                        '00000000-0000-4000-8000-000000000031',
                        '00000000-0000-4000-8000-000000000021',
                        'sensitivity',
                        'nope',
                        NULL,
                        'rule-1',
                        '2026-01-01T00:00:00Z'
                    )
                    """
                )

    def test_gate_evaluation_requires_reason_for_not_evaluated(self) -> None:
        with (
            PostgresContainer(image=RuntimePin().postgres_image()) as postgres,
            psycopg.connect(PostgresUrl().plain(postgres)) as connection,
        ):
            AlembicRunner(PostgresUrl().sync(postgres)).upgrade()
            self._insert_audit_row(connection)
            with connection.cursor() as cursor, pytest.raises(psycopg.Error):
                cursor.execute(
                    """
                    INSERT INTO gate_evaluation (
                        id, turn_id, gate_name, decision, reason,
                        policy_rule_id, evaluated_at
                    ) VALUES (
                        '00000000-0000-4000-8000-000000000032',
                        '00000000-0000-4000-8000-000000000021',
                        'sensitivity',
                        'not_evaluated',
                        NULL,
                        'rule-1',
                        '2026-01-01T00:00:00Z'
                    )
                    """
                )
            connection.rollback()
            self._insert_audit_row(connection)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO gate_evaluation (
                        id, turn_id, gate_name, decision, reason,
                        policy_rule_id, evaluated_at
                    ) VALUES (
                        '00000000-0000-4000-8000-000000000033',
                        '00000000-0000-4000-8000-000000000021',
                        'sensitivity',
                        'not_evaluated',
                        %s,
                        'rule-1',
                        '2026-01-01T00:00:00Z'
                    )
                    """,
                    (self._envelope(),),
                )

    def test_turn_audit_requires_existing_policy_version(self) -> None:
        with (
            PostgresContainer(image=RuntimePin().postgres_image()) as postgres,
            psycopg.connect(PostgresUrl().plain(postgres)) as connection,
        ):
            AlembicRunner(PostgresUrl().sync(postgres)).upgrade()
            with (
                connection.cursor() as cursor,
                pytest.raises(psycopg.Error, match="foreign key"),
            ):
                self._insert_learner_and_session(cursor)
                cursor.execute(
                    """
                    INSERT INTO turn_audit (
                        turn_id, session_id, turn_index, learner_prompt_redacted,
                        redacted_categories, retrieved_context_ids, model_revision,
                        template_version, decoding_params, output_before_checks,
                        output_after_checks, ai_disclosure, refused, safety_flags,
                        source_support, policy_version, previous_record_hash,
                        record_hash, recorded_at
                    ) VALUES (
                        '00000000-0000-4000-8000-000000000021',
                        '00000000-0000-4000-8000-000000000012',
                        0, %s, %s, '{}', 'sha', %s, %s, %s, %s, %s, false, %s, %s,
                        'missing-policy', 'a', 'b', '2026-01-01T00:00:00Z'
                    )
                    """,
                    (self._envelope(),) * 9,
                )

    def _assert_owner_mutation_raises(self, statement: str) -> None:
        with (
            PostgresContainer(image=RuntimePin().postgres_image()) as postgres,
            psycopg.connect(PostgresUrl().plain(postgres)) as connection,
        ):
            AlembicRunner(PostgresUrl().sync(postgres)).upgrade()
            self._insert_audit_row(connection)
            self._insert_gate_row(connection)
            with (
                connection.cursor() as cursor,
                pytest.raises(psycopg.Error, match="append-only"),
            ):
                cursor.execute(statement)

    def _insert_audit_row(self, connection: psycopg.Connection) -> None:
        with connection.cursor() as cursor:
            self._insert_learner_and_session(cursor)
            cursor.execute(
                """
                INSERT INTO policy_version (
                    version, allowed_actions, denied_actions, escalation_rules,
                    article_mappings, effective_from
                ) VALUES ('v1', %s, %s, %s, %s, '2026-01-01T00:00:00Z')
                ON CONFLICT (version) DO NOTHING
                """,
                (self._envelope(),) * 4,
            )
            cursor.execute(
                """
                INSERT INTO turn_audit (
                    turn_id, session_id, turn_index, learner_prompt_redacted,
                    redacted_categories, retrieved_context_ids, model_revision,
                    template_version, decoding_params, output_before_checks,
                    output_after_checks, ai_disclosure, refused, safety_flags,
                    source_support, policy_version, previous_record_hash,
                    record_hash, recorded_at
                ) VALUES (
                    '00000000-0000-4000-8000-000000000021',
                    '00000000-0000-4000-8000-000000000012',
                    0, %s, %s, '{}', 'sha', %s, %s, %s, %s, %s, false, %s, %s,
                    'v1', 'a', 'b', '2026-01-01T00:00:00Z'
                )
                ON CONFLICT (turn_id) DO NOTHING
                """,
                (self._envelope(),) * 9,
            )

    def _insert_gate_row(self, connection: psycopg.Connection) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO gate_evaluation (
                    id, turn_id, gate_name, decision, reason,
                    policy_rule_id, evaluated_at
                ) VALUES (
                    '00000000-0000-4000-8000-000000000041',
                    '00000000-0000-4000-8000-000000000021',
                    'sensitivity',
                    'pass',
                    %s,
                    'rule-1',
                    '2026-01-01T00:00:00Z'
                )
                ON CONFLICT (id) DO NOTHING
                """,
                (self._envelope(),),
            )

    def _insert_learner_and_session(self, cursor: psycopg.Cursor) -> None:
        envelope = self._envelope()
        cursor.execute(
            """
            INSERT INTO learner (
                learner_id, pseudonym, proficiency_level, retain_until
            ) VALUES (
                '00000000-0000-4000-8000-000000000011',
                %s, %s, '2026-12-01T00:00:00Z'
            )
            ON CONFLICT (learner_id) DO NOTHING
            """,
            (envelope, envelope),
        )
        cursor.execute(
            """
            INSERT INTO tutoring_session (
                id, tutor_id, learner_id, started_at
            ) VALUES (
                '00000000-0000-4000-8000-000000000012',
                %s,
                '00000000-0000-4000-8000-000000000011',
                '2026-01-01T00:00:00Z'
            )
            ON CONFLICT (id) DO NOTHING
            """,
            (envelope,),
        )

    def _tables(self, connection: psycopg.Connection) -> set[str]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public'
                """
            )
            return {row[0] for row in cursor.fetchall()}

    def _envelope(self) -> bytes:
        return b"\x01" + b"\x00" * 44
