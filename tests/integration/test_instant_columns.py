"""Every stored instant is full-precision ``timestamptz`` in the live catalogue.

The schema unit tests read the DDL text. This reads what Postgres built, so a
spelling the text checks miss, a domain over ``timestamp``, or a later
``ALTER COLUMN ... TYPE`` is caught too (DEC-0010, rule 9).
"""

import os

import psycopg
import pytest
from tests.support.migrated_database import MigratedDatabase

# A domain is resolved to its base type and typmod, so ``CREATE DOMAIN d AS
# timestamp(0)`` is reported as what it stores, not as ``d``.
_INSTANT_COLUMNS = """
    SELECT
        c.relname,
        a.attname,
        format_type(
            CASE WHEN t.typtype = 'd' THEN t.typbasetype ELSE t.oid END,
            CASE WHEN t.typtype = 'd' THEN t.typtypmod ELSE a.atttypmod END
        )
    FROM pg_attribute a
    JOIN pg_class c ON c.oid = a.attrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_type t ON t.oid = a.atttypid
    WHERE n.nspname = 'public'
      AND c.relkind IN ('r', 'p')
      AND a.attnum > 0
      AND NOT a.attisdropped
      AND (CASE WHEN t.typtype = 'd' THEN t.typbasetype ELSE t.oid END)
          IN ('timestamp'::regtype, 'timestamptz'::regtype)
    ORDER BY c.relname, a.attname
"""

_FULL_PRECISION = "timestamp with time zone"

_RECORDED_INSTANTS = {
    ("turn_audit", "recorded_at"),
    ("gate_evaluation", "evaluated_at"),
    ("human_action", "acted_at"),
    ("learner_history_event", "occurred_at"),
    ("tutoring_session", "started_at"),
    ("tutoring_session", "stopped_at"),
    ("policy_version", "effective_from"),
}


class InstantCatalogue:
    """The instant-typed columns of one live database."""

    def __init__(self, url: str) -> None:
        self._url = url

    def columns(self) -> dict[tuple[str, str], str]:
        with psycopg.connect(self._url) as connection:
            rows = connection.execute(_INSTANT_COLUMNS).fetchall()
        return {(table, column): kind for table, column, kind in rows}


class TestInstantColumns:
    def test_a_fresh_upgrade_stores_every_instant_as_timestamptz(
        self, fresh_database: str
    ) -> None:
        MigratedDatabase().upgrade(fresh_database)
        self._assert_full_precision(InstantCatalogue(fresh_database).columns())

    def test_the_sandbox_database_the_runner_migrated_passes_too(self) -> None:
        # ``make sandbox-test`` runs ``alembic upgrade head`` through the CLI
        # and ``env.py`` before pytest starts. This audits that database, not
        # one this test migrated itself.
        sandbox = os.environ.get("TUTOR_SANDBOX_URL")
        if not sandbox:
            pytest.skip("only inside make sandbox-test")
        self._assert_full_precision(InstantCatalogue(sandbox).columns())

    def test_the_audit_catches_a_zoneless_or_rounded_column(
        self, fresh_database: str
    ) -> None:
        with psycopg.connect(fresh_database, autocommit=True) as connection:
            connection.execute("CREATE DOMAIN rounded AS timestamptz(3)")
            connection.execute("CREATE TABLE probe (naive timestamp, coarse rounded)")
        columns = InstantCatalogue(fresh_database).columns()
        assert columns[("probe", "naive")] == "timestamp without time zone"
        assert columns[("probe", "coarse")] == "timestamp(3) with time zone"

    def _assert_full_precision(self, columns: dict[tuple[str, str], str]) -> None:
        assert columns.keys() >= _RECORDED_INSTANTS
        wrong = {key: kind for key, kind in columns.items() if kind != _FULL_PRECISION}
        assert wrong == {}
