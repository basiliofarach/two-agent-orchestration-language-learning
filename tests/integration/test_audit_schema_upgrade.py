"""A database stamped on the first audit revision still reaches the current shape."""

from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tutor_api.adapters.persistence.schema import ApplicationRole, SupersededAuditSchema
from tutor_api.settings import ApplicationSettings

_TURN = "00000000-0000-4000-8000-000000000021"
_SESSION = "00000000-0000-4000-8000-000000000012"
_CHUNK = "00000000-0000-4000-8000-000000000061"
_STAMPED = "46c99fd72506"


class PostgresUrl:
    """The driver flavour Alembic uses for one database."""

    def __init__(self, plain: str) -> None:
        self._plain = plain

    def sync(self) -> str:
        return self._plain.replace("postgresql://", "postgresql+psycopg://", 1)


class AlembicRunner:
    def __init__(self, url: str) -> None:
        root = Path(__file__).resolve().parents[2] / "tutor-api"
        self._config = Config(str(root / "alembic.ini"))
        self._config.set_main_option("script_location", str(root / "alembic"))
        self._config.set_main_option("sqlalchemy.url", url)

    def upgrade(self, revision: str) -> None:
        command.upgrade(self._config, revision)

    def stamp(self, revision: str) -> None:
        command.stamp(self._config, revision)

    def downgrade(self, revision: str) -> None:
        command.downgrade(self._config, revision)


class LegacyCatalogue:
    """The audit tables as revision 46c99fd72506 created them on the day it shipped."""

    def install(self, url: str) -> None:
        role = ApplicationRole(ApplicationSettings().postgres_app_user)
        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            for statement in SupersededAuditSchema(role).statements():
                cursor.execute(statement)

    def insert_cited_turn(self, url: str) -> None:
        envelope = self._envelope()
        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            self._parents(cursor, envelope)
            self._chunk(cursor, envelope)
            cursor.execute(
                """
                INSERT INTO turn_audit (
                    turn_id, session_id, turn_index,
                    learner_prompt_redacted, redacted_categories,
                    retrieved_context_ids,
                    model_revision, template_version, decoding_params,
                    output_before_checks, output_after_checks, ai_disclosure,
                    refused, safety_flags, source_support,
                    policy_version, previous_record_hash, record_hash, recorded_at
                ) VALUES (
                    %s, %s, 0,
                    %s, %s,
                    %s::uuid[],
                    'sha', %s, %s,
                    %s, %s, %s,
                    false, %s, %s,
                    'v1', 'a', 'b', '2026-01-01T00:00:00Z'
                )
                """,
                (
                    _TURN,
                    _SESSION,
                    envelope,
                    envelope,
                    [_CHUNK],
                    envelope,
                    envelope,
                    envelope,
                    envelope,
                    envelope,
                    envelope,
                    envelope,
                ),
            )

    def insert_orphan_citation(self, url: str) -> None:
        envelope = self._envelope()
        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            self._parents(cursor, envelope)
            cursor.execute(
                """
                INSERT INTO turn_audit (
                    turn_id, session_id, turn_index,
                    learner_prompt_redacted, redacted_categories,
                    retrieved_context_ids,
                    model_revision, template_version, decoding_params,
                    output_before_checks, output_after_checks, ai_disclosure,
                    refused, safety_flags, source_support,
                    policy_version, previous_record_hash, record_hash, recorded_at
                ) VALUES (
                    %s, %s, 0,
                    %s, %s,
                    ARRAY['00000000-0000-4000-8000-000000000099']::uuid[],
                    'sha', %s, %s,
                    %s, %s, %s,
                    false, %s, %s,
                    'v1', 'a', 'b', '2026-01-01T00:00:00Z'
                )
                """,
                (
                    _TURN,
                    _SESSION,
                    envelope,
                    envelope,
                    envelope,
                    envelope,
                    envelope,
                    envelope,
                    envelope,
                    envelope,
                    envelope,
                ),
            )

    def insert_action_blob(self, url: str) -> None:
        envelope = self._envelope()
        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            self._parents(cursor, envelope)
            cursor.execute(
                """
                INSERT INTO turn_audit (
                    turn_id, session_id, turn_index,
                    learner_prompt_redacted, redacted_categories,
                    retrieved_context_ids,
                    model_revision, template_version, decoding_params,
                    output_before_checks, output_after_checks, ai_disclosure,
                    refused, safety_flags, source_support, human_action,
                    policy_version, previous_record_hash, record_hash, recorded_at
                ) VALUES (
                    %s, %s, 0,
                    %s, %s,
                    ARRAY[]::uuid[],
                    'sha', %s, %s,
                    %s, %s, %s,
                    false, %s, %s, %s,
                    'v1', 'a', 'b', '2026-01-01T00:00:00Z'
                )
                """,
                (
                    _TURN,
                    _SESSION,
                    envelope,
                    envelope,
                    envelope,
                    envelope,
                    envelope,
                    envelope,
                    envelope,
                    envelope,
                    envelope,
                    envelope,
                ),
            )

    def _parents(self, cursor: psycopg.Cursor, envelope: bytes) -> None:
        cursor.execute(
            """
            INSERT INTO learner (
                learner_id, pseudonym, proficiency_level, retain_until
            ) VALUES (
                '00000000-0000-4000-8000-000000000011',
                %s, %s, '2026-12-01T00:00:00Z'
            )
            """,
            (envelope, envelope),
        )
        cursor.execute(
            """
            INSERT INTO tutoring_session (
                id, tutor_id, learner_id, started_at
            ) VALUES (
                %s, %s, '00000000-0000-4000-8000-000000000011',
                '2026-01-01T00:00:00Z'
            )
            """,
            (_SESSION, envelope),
        )
        cursor.execute(
            """
            INSERT INTO policy_version (
                version, allowed_actions, denied_actions, escalation_rules,
                article_mappings, effective_from
            ) VALUES ('v1', %s, %s, %s, %s, '2026-01-01T00:00:00Z')
            """,
            (envelope, envelope, envelope, envelope),
        )

    def _chunk(self, cursor: psycopg.Cursor, envelope: bytes) -> None:
        cursor.execute(
            """
            INSERT INTO kb_document (id, source_uri, version, review_status)
            VALUES (
                '00000000-0000-4000-8000-000000000060',
                'kb://library', '1', 'approved'
            )
            """
        )
        cursor.execute(
            """
            INSERT INTO kb_chunk (
                id, document_id, ordinal, content, embedding
            ) VALUES (%s, '00000000-0000-4000-8000-000000000060', 0, %s, %s)
            """,
            (_CHUNK, envelope, "[" + ",".join(["0"] * 768) + "]"),
        )

    def _envelope(self) -> bytes:
        return b"\x01" + b"\x00" * 44


class TestAuditSchemaUpgrade:
    def test_a_stamped_legacy_row_keeps_its_citation_across_downgrade(
        self, fresh_database: str
    ) -> None:
        runner = AlembicRunner(PostgresUrl(fresh_database).sync())
        catalogue = LegacyCatalogue()
        runner.upgrade("d97b5bda2b1c")
        catalogue.install(fresh_database)
        catalogue.insert_cited_turn(fresh_database)
        runner.stamp(_STAMPED)
        runner.upgrade("head")
        assert self._citation(fresh_database) == (_CHUNK, 0)
        assert not self._has_column(fresh_database, "retrieved_context_ids")
        assert self._has_unique_turn_index(fresh_database)
        runner.downgrade(_STAMPED)
        assert self._legacy_ids(fresh_database) == [_CHUNK]
        assert self._regclass(fresh_database, "turn_citation") is None
        runner.upgrade("head")
        assert self._citation(fresh_database) == (_CHUNK, 0)

    def test_a_legacy_citation_that_is_not_a_chunk_refuses_the_upgrade(
        self, fresh_database: str
    ) -> None:
        runner = AlembicRunner(PostgresUrl(fresh_database).sync())
        catalogue = LegacyCatalogue()
        runner.upgrade("d97b5bda2b1c")
        catalogue.install(fresh_database)
        catalogue.insert_orphan_citation(fresh_database)
        runner.stamp(_STAMPED)
        with pytest.raises(Exception, match="not a kb_chunk"):
            runner.upgrade("head")

    def test_a_registry_seeded_before_human_action_still_reaches_head(
        self, fresh_database: str
    ) -> None:
        runner = AlembicRunner(PostgresUrl(fresh_database).sync())
        catalogue = LegacyCatalogue()
        runner.upgrade("d97b5bda2b1c")
        self._drop_human_action_exemptions(fresh_database)
        catalogue.install(fresh_database)
        catalogue.insert_cited_turn(fresh_database)
        runner.stamp(_STAMPED)
        runner.upgrade("head")
        assert self._regclass(fresh_database, "human_action") == "human_action"
        assert self._action_exemption(fresh_database) == (
            "Non-personal control data. Stays cleartext so "
            "approve/edit/override/stop is a database constraint (DEC-0012)."
        )

    def test_a_legacy_action_blob_refuses_the_upgrade(
        self, fresh_database: str
    ) -> None:
        runner = AlembicRunner(PostgresUrl(fresh_database).sync())
        catalogue = LegacyCatalogue()
        runner.upgrade("d97b5bda2b1c")
        catalogue.install(fresh_database)
        catalogue.insert_action_blob(fresh_database)
        runner.stamp(_STAMPED)
        with pytest.raises(Exception, match="cannot be split"):
            runner.upgrade("head")

    def test_a_fresh_catalogue_downgrades_to_the_superseded_row(
        self, fresh_database: str
    ) -> None:
        runner = AlembicRunner(PostgresUrl(fresh_database).sync())
        runner.upgrade("head")
        runner.downgrade(_STAMPED)
        assert self._has_column(fresh_database, "retrieved_context_ids")
        assert self._has_column(fresh_database, "human_action")
        assert self._regclass(fresh_database, "turn_citation") is None
        assert self._regclass(fresh_database, "human_action") is None
        assert not self._has_unique_turn_index(fresh_database)
        runner.upgrade("head")
        assert not self._has_column(fresh_database, "retrieved_context_ids")
        assert self._regclass(fresh_database, "turn_citation") == "turn_citation"
        assert self._has_unique_turn_index(fresh_database)

    def test_a_stopped_turn_cannot_return_to_the_superseded_row(
        self, fresh_database: str
    ) -> None:
        runner = AlembicRunner(PostgresUrl(fresh_database).sync())
        runner.upgrade("head")
        envelope = LegacyCatalogue()._envelope()
        with (
            psycopg.connect(fresh_database) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                """
                INSERT INTO learner (
                    learner_id, pseudonym, proficiency_level, retain_until
                ) VALUES (
                    '00000000-0000-4000-8000-000000000011',
                    %s, %s, '2026-12-01T00:00:00Z'
                )
                """,
                (envelope, envelope),
            )
            cursor.execute(
                """
                INSERT INTO tutoring_session (
                    id, tutor_id, learner_id, started_at
                ) VALUES (%s, %s, '00000000-0000-4000-8000-000000000011',
                          '2026-01-01T00:00:00Z')
                """,
                (_SESSION, envelope),
            )
            cursor.execute(
                """
                INSERT INTO policy_version (
                    version, allowed_actions, denied_actions, escalation_rules,
                    article_mappings, effective_from
                ) VALUES ('v1', %s, %s, %s, %s, '2026-01-01T00:00:00Z')
                """,
                (envelope,) * 4,
            )
            cursor.execute(
                """
                INSERT INTO turn_audit (
                    turn_id, session_id, turn_index, learner_prompt_redacted,
                    redacted_categories, policy_version, previous_record_hash,
                    record_hash, recorded_at
                ) VALUES (
                    %s, %s, 0, %s, %s, 'v1', 'a', 'b', '2026-01-01T00:00:00Z'
                )
                """,
                (_TURN, _SESSION, envelope, envelope),
            )
        with pytest.raises(Exception, match="absent generation columns"):
            runner.downgrade(_STAMPED)
        assert self._regclass(fresh_database, "turn_citation") == "turn_citation"

    def _citation(self, url: str) -> tuple[str, int]:
        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT chunk_id::text, ordinal FROM turn_citation")
            row = cursor.fetchone()
        assert row is not None
        return (str(row[0]), int(row[1]))

    def _legacy_ids(self, url: str) -> list[str]:
        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT retrieved_context_ids::text[] FROM turn_audit")
            row = cursor.fetchone()
        assert row is not None
        return [str(value) for value in row[0]]

    def _has_column(self, url: str, column: str) -> bool:
        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'turn_audit'
                  AND column_name = %s
                """,
                (column,),
            )
            return cursor.fetchone() is not None

    def _has_unique_turn_index(self, url: str) -> bool:
        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT 1 FROM pg_constraint
                WHERE conname = 'turn_audit_session_turn'
                """
            )
            return cursor.fetchone() is not None

    def _drop_human_action_exemptions(self, url: str) -> None:
        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM protected_column_exemption
                WHERE schema_name = 'public' AND table_name = 'human_action'
                """
            )

    def _action_exemption(self, url: str) -> str:
        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT reason FROM protected_column_exemption
                WHERE schema_name = 'public'
                  AND table_name = 'human_action'
                  AND column_name = 'action'
                """
            )
            row = cursor.fetchone()
        assert row is not None
        return str(row[0])

    def _regclass(self, url: str, name: str) -> str | None:
        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass(%s)::text", (f"public.{name}",))
            row = cursor.fetchone()
        assert row is not None
        return None if row[0] is None else str(row[0])
