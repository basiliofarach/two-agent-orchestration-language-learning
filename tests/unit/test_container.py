"""The application container registers configuration and validates itself."""

import pytest
from pydantic import ValidationError

from tutor_api.container import ApplicationContainer, SettingsProvider
from tutor_api.di.lifetime import Lifetime
from tutor_api.routers.health import HealthStatus
from tutor_api.settings import ApplicationSettings


class TestSettingsProvider:
    def test_provides_the_settings_type(self) -> None:
        assert SettingsProvider().provides() is ApplicationSettings

    def test_is_a_singleton_because_configuration_is_process_wide(self) -> None:
        assert SettingsProvider().lifetime() is Lifetime.SINGLETON

    def test_requires_nothing(self) -> None:
        assert SettingsProvider().requires() == ()

    def test_creates_settings(self) -> None:
        assert isinstance(SettingsProvider().create({}), ApplicationSettings)


class TestApplicationContainer:
    def test_resolves_database_settings(self) -> None:
        container = ApplicationContainer().build()
        assert isinstance(container.resolve(ApplicationSettings), ApplicationSettings)

    def test_settings_are_read_once(self) -> None:
        container = ApplicationContainer().build()
        assert container.resolve(ApplicationSettings) is container.resolve(
            ApplicationSettings
        )

    def test_build_validates_the_graph(self) -> None:
        """An invalid graph must fail here, not on the first request."""
        assert ApplicationContainer().build() is not None

    def test_build_returns_a_new_container_each_time(self) -> None:
        """No module-level container: two builds share no state (rule 3)."""
        assert ApplicationContainer().build() is not ApplicationContainer().build()


class TestHealthStatus:
    def test_rejects_an_undeclared_field(self) -> None:
        with pytest.raises(ValidationError):
            HealthStatus(status="ok", database_configured=True, leaked="secret")

    def test_is_frozen(self) -> None:
        status = HealthStatus(status="ok", database_configured=True)
        with pytest.raises(ValidationError):
            status.status = "degraded"
