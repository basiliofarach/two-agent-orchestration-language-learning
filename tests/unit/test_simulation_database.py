"""The campaign database name and the URL Alembic is handed."""

import pytest

from tutor_api.curation.simulation_database import (
    DatabaseIdentifier,
    DatabaseUrl,
    SimulationDatabase,
)


class TestSimulationDatabase:
    def test_the_name_is_quoted_and_a_bad_name_is_refused(self) -> None:
        assert DatabaseIdentifier("tutor_sim").quoted() == '"tutor_sim"'
        with pytest.raises(ValueError, match="identifier"):
            DatabaseIdentifier("tutor-sim")

    def test_create_is_skipped_when_the_database_exists(self) -> None:
        database = SimulationDatabase("tutor_sim")
        assert database.create_statement(False) == 'CREATE DATABASE "tutor_sim"'
        assert database.create_statement(True) is None

    def test_the_owner_url_keeps_its_driver_and_changes_the_database(self) -> None:
        owner = "postgresql+psycopg://owner:secret@127.0.0.1:5432/tutor"
        urls = DatabaseUrl()
        assert urls.plain(owner) == "postgresql://owner:secret@127.0.0.1:5432/tutor"
        renamed = urls.renamed(owner, "tutor_sim")
        assert renamed == "postgresql+psycopg://owner:secret@127.0.0.1:5432/tutor_sim"
