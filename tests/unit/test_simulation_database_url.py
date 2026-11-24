"""The campaign database name and the URL Alembic is handed."""

import io

import pytest

from tutor_api.curation.simulation_database import (
    DatabaseIdentifier,
    DatabaseUrl,
    ResetRefused,
    SimulationDatabase,
    SimulationDatabaseMain,
)
from tutor_api.settings import ApplicationSettings


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
        verified = owner + "?sslmode=verify-full&sslrootcert=/tmp/ca.pem#root"
        assert urls.renamed(verified, "tutor_sim") == (
            "postgresql+psycopg://owner:secret@127.0.0.1:5432/tutor_sim"
            "?sslmode=verify-full&sslrootcert=/tmp/ca.pem#root"
        )

    def test_the_drop_forces_out_open_connections(self) -> None:
        assert SimulationDatabase("tutor_sim").drop_statement() == (
            'DROP DATABASE IF EXISTS "tutor_sim" WITH (FORCE)'
        )

    def test_a_reset_never_drops_the_database_the_owner_url_names(self) -> None:
        owner = "postgresql+psycopg://owner:secret@127.0.0.1:5432/tutor_sim"
        with pytest.raises(ResetRefused, match="owner URL names it"):
            SimulationDatabase("tutor_sim").reset(owner, discard_audit=True)

    def test_an_unknown_flag_is_a_usage_error(self) -> None:
        errors = io.StringIO()
        settings = ApplicationSettings(
            _env_file=None,  # type: ignore[call-arg]
            database_url="postgresql+psycopg://o:s@127.0.0.1:1/tutor",
        )
        status = SimulationDatabaseMain(
            settings, io.StringIO(), SimulationDatabase(), errors
        ).run(("--wipe",))
        assert status == 2
        assert "usage" in errors.getvalue()
