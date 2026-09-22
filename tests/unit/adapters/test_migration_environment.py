"""A URL the caller supplied wins; otherwise settings resolve one."""

from pathlib import Path

from tutor_api.adapters.persistence.database_url import MigrationDatabaseUrl
from tutor_api.adapters.persistence.migration_environment import MigrationEnvironment
from tutor_api.settings import ApplicationSettings


class RecordingConfig:
    """Stands in for alembic's Config, which needs a live migration to build."""

    def __init__(self, url: str | None = None) -> None:
        self.options: dict[str, str] = {}
        if url is not None:
            self.options["sqlalchemy.url"] = url

    def get_main_option(self, name: str, default: str | None = None) -> str | None:
        return self.options.get(name, default)

    def set_main_option(self, name: str, value: str) -> None:
        self.options[name] = value


def _url(tmp_path: Path) -> MigrationDatabaseUrl:
    settings = ApplicationSettings(
        _env_file=tmp_path / "absent.env",
        postgres_user="u",
        postgres_password="p",
        postgres_db="d",
    )
    return MigrationDatabaseUrl(settings)


class TestEnsureUrl:
    def test_resolves_when_the_config_has_none(self, tmp_path: Path) -> None:
        config = RecordingConfig()
        MigrationEnvironment(_url(tmp_path)).ensure_url(config)  # type: ignore[arg-type]
        assert config.options["sqlalchemy.url"] == (
            "postgresql+psycopg://u:p@127.0.0.1:5432/d"
        )

    def test_leaves_a_url_the_caller_supplied(self, tmp_path: Path) -> None:
        """The integration suite points Alembic at its own testcontainer."""
        config = RecordingConfig("postgresql+psycopg://test:test@127.0.0.1:1/probe")
        MigrationEnvironment(_url(tmp_path)).ensure_url(config)  # type: ignore[arg-type]
        assert config.options["sqlalchemy.url"] == (
            "postgresql+psycopg://test:test@127.0.0.1:1/probe"
        )

    def test_an_empty_url_is_treated_as_absent(self, tmp_path: Path) -> None:
        config = RecordingConfig("")
        MigrationEnvironment(_url(tmp_path)).ensure_url(config)  # type: ignore[arg-type]
        assert config.options["sqlalchemy.url"].startswith("postgresql+psycopg://")
