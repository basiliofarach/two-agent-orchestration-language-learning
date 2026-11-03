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
