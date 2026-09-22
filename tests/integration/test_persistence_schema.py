"""BE-05 and BE-06 schema, applied by Alembic to a fresh database."""

from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tutor_api.adapters.persistence.database import DatabaseEngine
from tutor_api.adapters.persistence.schema import ApplicationRole
from tutor_api.adapters.persistence.unit_of_work import (
    SqlAlchemyUnitOfWork,
    TransactionConnection,
)
from tutor_api.settings import ApplicationSettings
from tutor_core.domain.ports.unit_of_work import TransactionalWork

# Resolved with the environment excluded, not at whatever the shell happens to
# hold. This runs at import, before conftest's isolation fixture, so reading
# the ambient value here would disagree with the role the migration creates
# during the test — the migration runs after the fixture has cleared it.
_ROLE_NAME = ApplicationSettings(_env_file=None).postgres_app_user


class PostgresUrl:
    """The driver flavours one database is reached by."""

    def __init__(self, plain: str) -> None:
        self._plain = plain

    def sync(self) -> str:
        return self._plain.replace("postgresql://", "postgresql+psycopg://", 1)

    def async_url(self) -> str:
        return self._plain.replace("postgresql://", "postgresql+asyncpg://", 1)


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
    async def run(self, connection: TransactionConnection) -> None:
        await connection.execute("INSERT INTO uow_probe (id) VALUES (7)")


class ConflictingWrites(TransactionalWork):
    async def run(self, connection: TransactionConnection) -> None:
        await connection.execute("INSERT INTO uow_probe (id) VALUES (1)")
        await connection.execute("INSERT INTO uow_probe (id) VALUES (1)")


class TestPersistenceSchema:
    def test_migrate_forward_back_and_forward(self, fresh_database: str) -> None:
        with psycopg.connect(fresh_database) as connection:
            runner = AlembicRunner(PostgresUrl(fresh_database).sync())
            runner.upgrade()
            assert self._tables(connection) >= {"learner", "turn_audit"}
            runner.downgrade()
            assert "learner" not in self._tables(connection)
            assert "turn_audit" not in self._tables(connection)
            runner.upgrade()
            assert self._tables(connection) >= {"learner", "turn_audit", "kb_chunk"}

    def test_mismatched_embedding_dimension_raises(self, fresh_database: str) -> None:
        with psycopg.connect(fresh_database) as connection:
            AlembicRunner(PostgresUrl(fresh_database).sync()).upgrade()
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

    def test_learner_without_retain_until_raises(self, fresh_database: str) -> None:
        with psycopg.connect(fresh_database) as connection:
            AlembicRunner(PostgresUrl(fresh_database).sync()).upgrade()
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

    def test_session_requires_an_existing_learner(self, fresh_database: str) -> None:
        with psycopg.connect(fresh_database) as connection:
            AlembicRunner(PostgresUrl(fresh_database).sync()).upgrade()
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

    async def test_two_writes_roll_back_together(self, fresh_database: str) -> None:
        AlembicRunner(PostgresUrl(fresh_database).sync()).upgrade()
        with psycopg.connect(fresh_database) as connection:
            connection.execute("CREATE TABLE uow_probe (id integer PRIMARY KEY)")
            connection.commit()
        engine = DatabaseEngine(PostgresUrl(fresh_database).async_url())
        try:
            committed = await engine.connect()
            await SqlAlchemyUnitOfWork(committed).run(OneWrite())
            enlisted = await engine.connect()
            with pytest.raises(Exception, match="unique"):
                await SqlAlchemyUnitOfWork(enlisted).run(ConflictingWrites())
            with psycopg.connect(fresh_database) as connection:
                count = connection.execute("SELECT count(*) FROM uow_probe")
                row = count.fetchone()
            assert row is not None
            assert row[0] == 1
        finally:
            await engine.dispose()

    def test_update_against_turn_audit_raises_at_database_level(
        self, fresh_database: str
    ) -> None:
        self._assert_owner_mutation_raises(
            "UPDATE turn_audit SET refused = true", fresh_database
        )

    def test_delete_against_turn_audit_raises_at_database_level(
        self, fresh_database: str
    ) -> None:
        self._assert_owner_mutation_raises("DELETE FROM turn_audit", fresh_database)

    def test_update_against_gate_evaluation_raises_at_database_level(
        self, fresh_database: str
    ) -> None:
        self._assert_owner_mutation_raises(
            "UPDATE gate_evaluation SET decision = 'stop'", fresh_database
        )

    def test_delete_against_gate_evaluation_raises_at_database_level(
        self, fresh_database: str
    ) -> None:
        self._assert_owner_mutation_raises(
            "DELETE FROM gate_evaluation", fresh_database
        )

    def test_permission_stop_stores_null_generation_and_a_later_tutor_action(
        self, fresh_database: str
    ) -> None:
        with psycopg.connect(fresh_database) as connection:
            AlembicRunner(PostgresUrl(fresh_database).sync()).upgrade()
            self._insert_stopped_turn(connection)
            self._insert_permission_stop_gates(connection)
            self._insert_tutor_edit(connection)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT model_revision, output_before_checks, output_after_checks
                    FROM turn_audit
                    """
                )
                generation = cursor.fetchone()
                cursor.execute("SELECT count(*) FROM turn_citation")
                citations = cursor.fetchone()
                cursor.execute(
                    """
                    SELECT gate_name, decision
                    FROM gate_evaluation
                    ORDER BY gate_name
                    """
                )
                gates = cursor.fetchall()
                cursor.execute("SELECT action FROM human_action")
                action = cursor.fetchone()
        assert generation == (None, None, None)
        assert citations is not None
        assert citations[0] == 0
        assert gates == [
            ("conflict_and_ambiguity", "not_evaluated"),
            ("context_and_permission", "stop"),
            ("drift_and_anomaly", "not_evaluated"),
            ("sensitivity_and_high_stakes", "not_evaluated"),
        ]
        assert action == ("edit",)

    def test_a_revision_without_outputs_is_rejected(self, fresh_database: str) -> None:
        with psycopg.connect(fresh_database) as connection:
            AlembicRunner(PostgresUrl(fresh_database).sync()).upgrade()
            with (
                connection.cursor() as cursor,
                pytest.raises(psycopg.Error, match="turn_audit_generation_together"),
            ):
                self._insert_learner_and_session(cursor)
                self._insert_policy(cursor)
                cursor.execute(
                    """
                    INSERT INTO turn_audit (
                        turn_id, session_id, turn_index, learner_prompt_redacted,
                        redacted_categories, model_revision, policy_version,
                        previous_record_hash, record_hash, recorded_at
                    ) VALUES (
                        '00000000-0000-4000-8000-000000000021',
                        '00000000-0000-4000-8000-000000000012',
                        0, %s, %s, 'sha', 'v1', 'a', 'b', '2026-01-01T00:00:00Z'
                    )
                    """,
                    (self._envelope(), self._envelope()),
                )

    def test_an_edit_without_output_is_rejected(self, fresh_database: str) -> None:
        with psycopg.connect(fresh_database) as connection:
            AlembicRunner(PostgresUrl(fresh_database).sync()).upgrade()
            self._insert_stopped_turn(connection)
            with (
                connection.cursor() as cursor,
                pytest.raises(psycopg.Error, match="human_action_edit_has_output"),
            ):
                cursor.execute(
                    """
                    INSERT INTO human_action (
                        id, turn_id, tutor_id, action, edited_output, acted_at
                    ) VALUES (
                        '00000000-0000-4000-8000-000000000051',
                        '00000000-0000-4000-8000-000000000021',
                        %s, 'edit', NULL, '2026-01-01T00:00:00Z'
                    )
                    """,
                    (self._envelope(),),
                )

    def test_a_citation_requires_an_existing_chunk(self, fresh_database: str) -> None:
        with psycopg.connect(fresh_database) as connection:
            AlembicRunner(PostgresUrl(fresh_database).sync()).upgrade()
            self._insert_stopped_turn(connection)
            with (
                connection.cursor() as cursor,
                pytest.raises(psycopg.Error, match="foreign key"),
            ):
                cursor.execute(
                    """
                    INSERT INTO turn_citation (turn_id, chunk_id, ordinal)
                    VALUES (
                        '00000000-0000-4000-8000-000000000021',
                        '00000000-0000-4000-8000-000000000099',
                        0
                    )
                    """
                )
            connection.rollback()
            self._insert_stopped_turn(connection)
            self._insert_chunk(connection)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO turn_citation (turn_id, chunk_id, ordinal)
                    VALUES (
                        '00000000-0000-4000-8000-000000000021',
                        '00000000-0000-4000-8000-000000000061',
                        0
                    )
                    """
                )
                cursor.execute("SELECT chunk_id FROM turn_citation")
                cited = cursor.fetchone()
        assert cited is not None
        assert str(cited[0]) == "00000000-0000-4000-8000-000000000061"

    def test_update_against_human_action_raises_at_database_level(
        self, fresh_database: str
    ) -> None:
        with psycopg.connect(fresh_database) as connection:
            AlembicRunner(PostgresUrl(fresh_database).sync()).upgrade()
            self._insert_stopped_turn(connection)
            self._insert_tutor_edit(connection)
            with (
                connection.cursor() as cursor,
                pytest.raises(psycopg.Error, match="append-only"),
            ):
                cursor.execute("UPDATE human_action SET action = 'stop'")

    def test_delete_against_turn_citation_raises_at_database_level(
        self, fresh_database: str
    ) -> None:
        with psycopg.connect(fresh_database) as connection:
            AlembicRunner(PostgresUrl(fresh_database).sync()).upgrade()
            self._insert_stopped_turn(connection)
            self._insert_chunk(connection)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO turn_citation (turn_id, chunk_id, ordinal)
                    VALUES (
                        '00000000-0000-4000-8000-000000000021',
                        '00000000-0000-4000-8000-000000000061',
                        0
                    )
                    """
                )
            with (
                connection.cursor() as cursor,
                pytest.raises(psycopg.Error, match="append-only"),
            ):
                cursor.execute("DELETE FROM turn_citation")

    def test_application_role_has_no_update_or_delete_grant(
        self, fresh_database: str
    ) -> None:
        with psycopg.connect(fresh_database) as connection:
            AlembicRunner(PostgresUrl(fresh_database).sync()).upgrade()
            self._insert_audit_row(connection)
            connection.commit()
            with connection.cursor() as cursor, pytest.raises(psycopg.Error):
                cursor.execute(f"SET ROLE {ApplicationRole(_ROLE_NAME).identifier()}")
                cursor.execute("UPDATE turn_audit SET refused = true")

    def test_truncate_of_audit_table_is_refused_for_application_role(
        self, fresh_database: str
    ) -> None:
        with psycopg.connect(fresh_database) as connection:
            AlembicRunner(PostgresUrl(fresh_database).sync()).upgrade()
            with connection.cursor() as cursor, pytest.raises(psycopg.Error):
                cursor.execute(f"SET ROLE {ApplicationRole(_ROLE_NAME).identifier()}")
                cursor.execute("TRUNCATE turn_audit")

    def test_gate_evaluation_rejects_unknown_decision(
        self, fresh_database: str
    ) -> None:
        with psycopg.connect(fresh_database) as connection:
            AlembicRunner(PostgresUrl(fresh_database).sync()).upgrade()
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

    def test_gate_evaluation_requires_reason_for_not_evaluated(
        self, fresh_database: str
    ) -> None:
        with psycopg.connect(fresh_database) as connection:
            AlembicRunner(PostgresUrl(fresh_database).sync()).upgrade()
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

    def test_turn_audit_requires_existing_policy_version(
        self, fresh_database: str
    ) -> None:
        with psycopg.connect(fresh_database) as connection:
            AlembicRunner(PostgresUrl(fresh_database).sync()).upgrade()
            with (
                connection.cursor() as cursor,
                pytest.raises(psycopg.Error, match="foreign key"),
            ):
                self._insert_learner_and_session(cursor)
                cursor.execute(
                    """
                    INSERT INTO turn_audit (
                        turn_id, session_id, turn_index, learner_prompt_redacted,
                        redacted_categories, model_revision, template_version,
                        decoding_params, output_before_checks, output_after_checks,
                        ai_disclosure, refused, safety_flags, source_support,
                        policy_version, previous_record_hash, record_hash,
                        recorded_at
                    ) VALUES (
                        '00000000-0000-4000-8000-000000000021',
                        '00000000-0000-4000-8000-000000000012',
                        0, %s, %s, 'sha', %s, %s, %s, %s, %s, false, %s, %s,
                        'missing-policy', 'a', 'b', '2026-01-01T00:00:00Z'
                    )
                    """,
                    (self._envelope(),) * 9,
                )

    def _assert_owner_mutation_raises(
        self, statement: str, fresh_database: str
    ) -> None:
        with psycopg.connect(fresh_database) as connection:
            AlembicRunner(PostgresUrl(fresh_database).sync()).upgrade()
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
            self._insert_policy(cursor)
            cursor.execute(
                """
                INSERT INTO turn_audit (
                    turn_id, session_id, turn_index, learner_prompt_redacted,
                    redacted_categories, model_revision, template_version,
                    decoding_params, output_before_checks, output_after_checks,
                    ai_disclosure, refused, safety_flags, source_support,
                    policy_version, previous_record_hash, record_hash, recorded_at
                ) VALUES (
                    '00000000-0000-4000-8000-000000000021',
                    '00000000-0000-4000-8000-000000000012',
                    0, %s, %s, 'sha', %s, %s, %s, %s, %s, false, %s, %s,
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

    def _insert_policy(self, cursor: psycopg.Cursor) -> None:
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

    def _insert_stopped_turn(self, connection: psycopg.Connection) -> None:
        with connection.cursor() as cursor:
            self._insert_learner_and_session(cursor)
            self._insert_policy(cursor)
            cursor.execute(
                """
                INSERT INTO turn_audit (
                    turn_id, session_id, turn_index, learner_prompt_redacted,
                    redacted_categories, policy_version, previous_record_hash,
                    record_hash, recorded_at
                ) VALUES (
                    '00000000-0000-4000-8000-000000000021',
                    '00000000-0000-4000-8000-000000000012',
                    0, %s, %s, 'v1', 'a', 'b', '2026-01-01T00:00:00Z'
                )
                ON CONFLICT (turn_id) DO NOTHING
                """,
                (self._envelope(), self._envelope()),
            )

    def _insert_permission_stop_gates(self, connection: psycopg.Connection) -> None:
        rows = (
            (
                "00000000-0000-4000-8000-000000000071",
                "context_and_permission",
                "stop",
            ),
            (
                "00000000-0000-4000-8000-000000000072",
                "conflict_and_ambiguity",
                "not_evaluated",
            ),
            (
                "00000000-0000-4000-8000-000000000073",
                "sensitivity_and_high_stakes",
                "not_evaluated",
            ),
            (
                "00000000-0000-4000-8000-000000000074",
                "drift_and_anomaly",
                "not_evaluated",
            ),
        )
        with connection.cursor() as cursor:
            for row_id, gate_name, decision in rows:
                cursor.execute(
                    """
                    INSERT INTO gate_evaluation (
                        id, turn_id, gate_name, decision, reason,
                        policy_rule_id, evaluated_at
                    ) VALUES (
                        %s,
                        '00000000-0000-4000-8000-000000000021',
                        %s,
                        %s,
                        %s,
                        'perm-1',
                        '2026-01-01T00:00:00Z'
                    )
                    """,
                    (row_id, gate_name, decision, self._envelope()),
                )

    def _insert_tutor_edit(self, connection: psycopg.Connection) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO human_action (
                    id, turn_id, tutor_id, action, edited_output, acted_at
                ) VALUES (
                    '00000000-0000-4000-8000-000000000051',
                    '00000000-0000-4000-8000-000000000021',
                    %s, 'edit', %s, '2026-01-01T00:00:00Z'
                )
                ON CONFLICT (id) DO NOTHING
                """,
                (self._envelope(), self._envelope()),
            )

    def _insert_chunk(self, connection: psycopg.Connection) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO kb_document (id, source_uri, version, review_status)
                VALUES (
                    '00000000-0000-4000-8000-000000000060',
                    'kb://library',
                    '1',
                    'approved'
                )
                ON CONFLICT (id) DO NOTHING
                """
            )
            cursor.execute(
                """
                INSERT INTO kb_chunk (
                    id, document_id, ordinal, content, embedding
                ) VALUES (
                    '00000000-0000-4000-8000-000000000061',
                    '00000000-0000-4000-8000-000000000060',
                    0,
                    %s,
                    %s
                )
                ON CONFLICT (id) DO NOTHING
                """,
                (self._envelope(), "[" + ",".join(["0"] * 768) + "]"),
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
