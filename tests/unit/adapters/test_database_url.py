"""Alembic's URL comes from settings, never from alembic.ini."""

from pathlib import Path

import pytest

from tutor_api.adapters.persistence.database_url import MigrationDatabaseUrl
from tutor_api.settings import ApplicationSettings

_ENV_FILE = """POSTGRES_USER=tutor_owner
POSTGRES_PASSWORD=tutor_owner
POSTGRES_DB=tutor
POSTGRES_PORT=5433
POSTGRES_HOST=127.0.0.1
"""


class EnvFile:
    """A throwaway .env, so a developer's real one cannot change the result."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def settings(
        self,
        body: str = _ENV_FILE,
        **overrides: object,
    ) -> ApplicationSettings:
        path = self._root / ".env"
        path.write_text(body, encoding="utf-8")
        return ApplicationSettings(_env_file=path, **overrides)

    def absent(self, **overrides: object) -> ApplicationSettings:
        return ApplicationSettings(
            _env_file=self._root / "absent.env",
            **overrides,
        )


class TestUrlFromParts:
    def test_composes_from_the_env_file(self, tmp_path: Path) -> None:
        url = MigrationDatabaseUrl(EnvFile(tmp_path).settings())
        assert url.value() == (
            "postgresql+psycopg://tutor_owner:tutor_owner@127.0.0.1:5433/tutor"
        )

    def test_process_environment_overrides_the_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("POSTGRES_PASSWORD", "from-shell")
        url = MigrationDatabaseUrl(EnvFile(tmp_path).settings())
        assert "from-shell" in url.value()
        assert ":tutor_owner@" not in url.value()

    def test_defaults_host_and_port_when_absent(self, tmp_path: Path) -> None:
        body = "POSTGRES_USER=u\nPOSTGRES_PASSWORD=p\nPOSTGRES_DB=d\n"
        url = MigrationDatabaseUrl(EnvFile(tmp_path).settings(body))
        assert url.value() == "postgresql+psycopg://u:p@127.0.0.1:5432/d"

    def test_percent_encodes_credentials(self, tmp_path: Path) -> None:
        body = "POSTGRES_USER=u\nPOSTGRES_PASSWORD=p@ss:w/ord\nPOSTGRES_DB=d\n"
        url = MigrationDatabaseUrl(EnvFile(tmp_path).settings(body))
        # Unencoded, the @ would be read as the start of the host.
        assert url.value() == "postgresql+psycopg://u:p%40ss%3Aw%2Ford@127.0.0.1:5432/d"

    def test_missing_value_names_what_to_set(self, tmp_path: Path) -> None:
        settings = EnvFile(tmp_path).absent(
            postgres_user="u", postgres_password=None, postgres_db="d"
        )
        with pytest.raises(ValueError, match="POSTGRES_PASSWORD is not set"):
            MigrationDatabaseUrl(settings).value()

    def test_absent_env_file_is_not_an_error(self, tmp_path: Path) -> None:
        settings = EnvFile(tmp_path).absent(
            postgres_user="u", postgres_password="p", postgres_db="d"
        )
        assert MigrationDatabaseUrl(settings).value() == (
            "postgresql+psycopg://u:p@127.0.0.1:5432/d"
        )


class TestDatabaseUrlOverride:
    def test_database_url_wins_over_the_parts(self, tmp_path: Path) -> None:
        settings = EnvFile(tmp_path).settings(
            database_url="postgresql+psycopg://a:b@db:5432/other"
        )
        assert MigrationDatabaseUrl(settings).value() == (
            "postgresql+psycopg://a:b@db:5432/other"
        )

    @pytest.mark.parametrize(
        "given",
        [
            "postgresql+asyncpg://a:b@db:5432/x",
            "postgresql+psycopg2://a:b@db:5432/x",
            "postgresql://a:b@db:5432/x",
            "postgres://a:b@db:5432/x",
        ],
    )
    def test_driver_is_normalised_to_psycopg(self, tmp_path: Path, given: str) -> None:
        settings = EnvFile(tmp_path).absent(database_url=given)
        assert MigrationDatabaseUrl(settings).value() == (
            "postgresql+psycopg://a:b@db:5432/x"
        )


class TestUnknownDriver:
    def test_a_driver_it_does_not_recognise_passes_through(
        self, tmp_path: Path
    ) -> None:
        settings = EnvFile(tmp_path).absent(database_url="sqlite:///local.db")
        assert MigrationDatabaseUrl(settings).value() == "sqlite:///local.db"


class TestConfigParserEscaping:
    def test_percent_is_doubled_for_interpolation(self, tmp_path: Path) -> None:
        """ConfigParser reads a lone % as the start of a substitution."""
        body = "POSTGRES_USER=u\nPOSTGRES_PASSWORD=p@ss\nPOSTGRES_DB=d\n"
        url = MigrationDatabaseUrl(EnvFile(tmp_path).settings(body))
        assert "%40" in url.value()
        assert "%%40" in url.escaped()

    def test_a_url_without_percent_is_unchanged(self, tmp_path: Path) -> None:
        url = MigrationDatabaseUrl(EnvFile(tmp_path).settings())
        assert url.escaped() == url.value()
