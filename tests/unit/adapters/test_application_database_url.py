"""The application connects as the application role, through asyncpg."""

import pytest

from tutor_api.adapters.persistence.database_url import ApplicationDatabaseUrl
from tutor_api.settings import ApplicationSettings


class Configured:
    """Settings with no ``.env``. The owner is named unless a test overrides it."""

    def settings(self, **values: object) -> ApplicationSettings:
        named = {"postgres_user": "tutor_owner", **values}
        return ApplicationSettings(_env_file=None, **named)  # type: ignore[call-arg]


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

    def test_an_override_as_the_application_role_is_normalised_to_asyncpg(self) -> None:
        settings = Configured().settings(
            postgres_app_user="tutor_app",
            application_database_url="postgresql://tutor_app:p%40ss@db:5432/tutor",
        )
        assert (
            ApplicationDatabaseUrl(settings).value()
            == "postgresql+asyncpg://tutor_app:p%40ss@db:5432/tutor"
        )

    def test_an_override_as_the_owner_is_rejected(self) -> None:
        settings = Configured().settings(
            postgres_app_user="tutor_app",
            application_database_url="postgresql://tutor_owner:secret@db:5432/tutor",
        )
        with pytest.raises(ValueError, match="not the application role 'tutor_app'"):
            ApplicationDatabaseUrl(settings).value()

    def test_an_override_is_rejected_when_the_application_role_is_the_owner(
        self,
    ) -> None:
        settings = Configured().settings(
            postgres_user="tutor_owner",
            postgres_app_user="tutor_owner",
            application_database_url="postgresql://tutor_owner:secret@db:5432/tutor",
        )
        with pytest.raises(ValueError, match="is the migration owner"):
            ApplicationDatabaseUrl(settings).value()

    def test_a_composed_url_is_rejected_when_the_application_role_is_the_owner(
        self,
    ) -> None:
        settings = Configured().settings(
            postgres_user="tutor_owner",
            postgres_db="tutor",
            postgres_app_user="tutor_owner",
            postgres_app_password="secret",
        )
        with pytest.raises(ValueError, match="is the migration owner"):
            ApplicationDatabaseUrl(settings).value()

    def test_the_owner_named_only_by_database_url_is_rejected(self) -> None:
        settings = Configured().settings(
            postgres_user=None,
            database_url="postgresql://tutor_owner:secret@db:5432/tutor",
            postgres_app_user="tutor_owner",
            application_database_url="postgresql://tutor_owner:secret@db:5432/tutor",
        )
        with pytest.raises(ValueError, match="is the migration owner"):
            ApplicationDatabaseUrl(settings).value()

    def test_database_url_names_the_owner_over_postgres_user(self) -> None:
        settings = Configured().settings(
            postgres_user="someone_else",
            database_url="postgresql://tutor_owner:secret@db:5432/tutor",
            postgres_app_user="tutor_owner",
            application_database_url="postgresql://tutor_owner:secret@db:5432/tutor",
        )
        with pytest.raises(ValueError, match="is the migration owner"):
            ApplicationDatabaseUrl(settings).value()

    def test_an_unknown_owner_is_rejected_rather_than_assumed_distinct(
        self,
    ) -> None:
        settings = Configured().settings(
            postgres_user=None,
            postgres_app_user="tutor_owner",
            application_database_url="postgresql://tutor_owner:secret@db:5432/tutor",
        )
        with pytest.raises(ValueError, match="cannot tell the migration owner"):
            ApplicationDatabaseUrl(settings).value()

    def test_an_override_without_a_user_is_rejected(self) -> None:
        settings = Configured().settings(
            application_database_url="postgresql://db:5432/tutor"
        )
        with pytest.raises(ValueError, match="has no user"):
            ApplicationDatabaseUrl(settings).value()

    def test_a_missing_password_names_what_to_set(self) -> None:
        settings = Configured().settings(postgres_db="tutor")
        with pytest.raises(ValueError, match="POSTGRES_APP_PASSWORD is not set"):
            ApplicationDatabaseUrl(settings).value()
