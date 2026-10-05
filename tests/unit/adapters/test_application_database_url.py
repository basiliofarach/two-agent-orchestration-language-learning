"""The application connects as the application role, through asyncpg."""

import pytest

from tutor_api.adapters.persistence.database_url import ApplicationDatabaseUrl
from tutor_api.settings import ApplicationSettings


class Configured:
    def settings(self, **values: object) -> ApplicationSettings:
        return ApplicationSettings(_env_file=None, **values)  # type: ignore[call-arg]


class TestApplicationDatabaseUrl:
    def test_composes_the_application_role_not_the_owner(self) -> None:
        settings = Configured().settings(
            postgres_user="tutor_owner",
            postgres_password="owner-secret",
            postgres_db="tutor",
            postgres_app_user="tutor_app",
            postgres_app_password="app-secret",
            postgres_port=5433,
        )
        url = ApplicationDatabaseUrl(settings).value()
        assert url == "postgresql+asyncpg://tutor_app:app-secret@127.0.0.1:5433/tutor"
        assert "owner" not in url

    def test_percent_encodes_credentials(self) -> None:
        settings = Configured().settings(
            postgres_db="tutor", postgres_app_password="p@ss/word"
        )
        assert "p%40ss%2Fword@" in ApplicationDatabaseUrl(settings).value()

    def test_an_override_wins_and_is_normalised_to_asyncpg(self) -> None:
        settings = Configured().settings(
            application_database_url="postgresql://u:p@db:5432/tutor"
        )
        assert (
            ApplicationDatabaseUrl(settings).value()
            == "postgresql+asyncpg://u:p@db:5432/tutor"
        )

    def test_a_missing_password_names_what_to_set(self) -> None:
        settings = Configured().settings(postgres_db="tutor")
        with pytest.raises(ValueError, match="POSTGRES_APP_PASSWORD is not set"):
            ApplicationDatabaseUrl(settings).value()
