"""The campaign database is created on the server the owner can already reach."""

import psycopg

from tutor_api.curation.simulation_database import SimulationDatabase


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
