"""The campaign database is created on the server the owner can already reach."""

import io

import psycopg

from tutor_api.curation.simulation_database import (
    SimulationDatabase,
    SimulationDatabaseMain,
)
from tutor_api.settings import ApplicationSettings


class TestSimulationDatabase:
    def test_ensure_creates_the_database_and_the_vector_extension(
        self, postgres_maintenance_url: str
    ) -> None:
        name = "tutor_sim_it"
        created = SimulationDatabase(name).ensure(postgres_maintenance_url)
        try:
            with psycopg.connect(created) as connection:
                row = connection.execute(
                    "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
                ).fetchone()
            assert row is not None
            again = SimulationDatabase(name).ensure(postgres_maintenance_url)
            assert again.endswith(f"/{name}")
        finally:
            with psycopg.connect(postgres_maintenance_url, autocommit=True) as admin:
                admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')

    def test_the_process_entry_prints_the_owner_url_of_the_created_database(
        self, postgres_maintenance_url: str
    ) -> None:
        name = "tutor_sim_entry_it"
        settings = ApplicationSettings(
            _env_file=None,  # type: ignore[call-arg]
            database_url=postgres_maintenance_url,
        )
        output = io.StringIO()
        try:
            status = SimulationDatabaseMain(
                settings, output, SimulationDatabase(name)
            ).run()
            assert status == 0
            printed = output.getvalue()
            assert printed.endswith(f"/{name}\n")
            assert printed.startswith("postgresql+psycopg://")
            with psycopg.connect(
                printed.strip().replace("postgresql+psycopg://", "postgresql://", 1)
            ) as connection:
                row = connection.execute(
                    "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
                ).fetchone()
            assert row is not None
        finally:
            with psycopg.connect(postgres_maintenance_url, autocommit=True) as admin:
                admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')

    def test_a_reset_drops_old_rows_and_leaves_an_empty_database(
        self, postgres_maintenance_url: str
    ) -> None:
        name = "tutor_sim_reset_it"
        database = SimulationDatabase(name)
        created = database.ensure(postgres_maintenance_url)
        try:
            with psycopg.connect(created, autocommit=True) as connection:
                connection.execute("CREATE TABLE kb_chunk (id int)")
                connection.execute("INSERT INTO kb_chunk VALUES (1)")
            reset = database.reset(postgres_maintenance_url, discard_audit=False)
            with psycopg.connect(reset) as connection:
                gone = connection.execute("SELECT to_regclass('kb_chunk')").fetchone()
                vector = connection.execute(
                    "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
                ).fetchone()
            assert gone == (None,)
            assert vector is not None
        finally:
            with psycopg.connect(postgres_maintenance_url, autocommit=True) as admin:
                admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')

    def test_audit_records_stop_a_reset_unless_the_operator_discards_them(
        self, postgres_maintenance_url: str
    ) -> None:
        name = "tutor_sim_audit_it"
        database = SimulationDatabase(name)
        created = database.ensure(postgres_maintenance_url)
        settings = ApplicationSettings(
            _env_file=None,  # type: ignore[call-arg]
            database_url=postgres_maintenance_url,
        )
        try:
            with psycopg.connect(created, autocommit=True) as connection:
                connection.execute("CREATE TABLE turn_audit (id int)")
                connection.execute("INSERT INTO turn_audit VALUES (1), (2)")
            errors = io.StringIO()
            output = io.StringIO()
            entry = SimulationDatabaseMain(settings, output, database, errors)
            assert entry.run(("--reset",)) == 1
            assert "holds 2 audit records" in errors.getvalue()
            assert output.getvalue() == ""
            with psycopg.connect(created) as connection:
                kept = connection.execute("SELECT count(*) FROM turn_audit").fetchone()
            assert kept == (2,)

            assert entry.run(("--reset", "--discard-audit")) == 0
            assert output.getvalue().endswith(f"/{name}\n")
            with psycopg.connect(created) as connection:
                gone = connection.execute("SELECT to_regclass('turn_audit')").fetchone()
            assert gone == (None,)
        finally:
            with psycopg.connect(postgres_maintenance_url, autocommit=True) as admin:
                admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')

    def test_an_audit_table_left_empty_does_not_stop_a_reset(
        self, postgres_maintenance_url: str
    ) -> None:
        name = "tutor_sim_empty_audit_it"
        database = SimulationDatabase(name)
        created = database.ensure(postgres_maintenance_url)
        try:
            with psycopg.connect(created, autocommit=True) as connection:
                connection.execute("CREATE TABLE turn_audit (id int)")
            reset = database.reset(postgres_maintenance_url, discard_audit=False)
            assert reset.endswith(f"/{name}")
        finally:
            with psycopg.connect(postgres_maintenance_url, autocommit=True) as admin:
                admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')

    def test_a_reset_of_an_absent_database_creates_it(
        self, postgres_maintenance_url: str
    ) -> None:
        name = "tutor_sim_absent_it"
        try:
            created = SimulationDatabase(name).reset(
                postgres_maintenance_url, discard_audit=False
            )
            with psycopg.connect(created) as connection:
                row = connection.execute(
                    "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
                ).fetchone()
            assert row is not None
        finally:
            with psycopg.connect(postgres_maintenance_url, autocommit=True) as admin:
                admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
