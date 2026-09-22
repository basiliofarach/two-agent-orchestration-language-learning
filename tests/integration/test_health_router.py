"""The router receives settings from the container, through its signature."""

from collections.abc import Iterator, Mapping
from typing import Annotated, get_args, get_origin, get_type_hints

import pytest
from fastapi.params import Depends
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from tutor_api.container import ApplicationContainer
from tutor_api.di.container import Container
from tutor_api.di.dependency import Provide
from tutor_api.di.lifetime import Lifetime
from tutor_api.di.provider import Provider
from tutor_api.main import Application
from tutor_api.routers.health import HealthRouter
from tutor_api.settings import ApplicationSettings


class UnconfiguredSettingsProvider(Provider):
    """Registers settings with no database target, to prove injection."""

    def provides(self) -> type:
        return ApplicationSettings

    def lifetime(self) -> Lifetime:
        return Lifetime.SINGLETON

    def requires(self) -> tuple[type, ...]:
        return ()

    def create(self, resolved: Mapping[type, object]) -> object:
        return ApplicationSettings(
            _env_file=None,
            postgres_db=None,
            database_url=None,
        )


class ConfiguredSettingsProvider(Provider):
    """Registers settings with a known database target.

    A test states its own configuration. Reading the developer's
    ``tutor-api/.env`` would make the result depend on whether that file
    exists and on the directory pytest was started from: ``env_file=".env"``
    is resolved against the working directory, so it is found from
    ``tutor-api/`` and not from the repository root, which is where the suite
    actually runs.
    """

    def provides(self) -> type:
        return ApplicationSettings

    def lifetime(self) -> Lifetime:
        return Lifetime.SINGLETON

    def requires(self) -> tuple[type, ...]:
        return ()

    def create(self, resolved: Mapping[type, object]) -> object:
        return ApplicationSettings(
            _env_file=None,
            postgres_user="tutor_owner",
            postgres_password="never-in-a-response",
            postgres_db="tutor",
        )


def _client(provider: Provider) -> TestClient:
    container = Container((provider,))
    container.validate()
    return TestClient(Application(container).asgi())


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A client over a graph whose configuration the test states itself."""
    with _client(ConfiguredSettingsProvider()) as started:
        yield started


class TestHealthRouter:
    def test_returns_ok_with_the_graph_wired(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "database_configured": True}

    def test_settings_are_injected_not_constructed(self) -> None:
        """Swap the provider; the handler must follow the container.

        A handler that built its own ``Settings`` — or read the
        environment — would ignore this and still answer ``True``.
        """
        with _client(UnconfiguredSettingsProvider()) as started:
            body = started.get("/health").json()
        assert body == {"status": "ok", "database_configured": False}

    def test_the_real_container_wires_the_route(self) -> None:
        """The graph ``main.py`` composes must serve the route.

        Only the shape is asserted. Whether a database is configured depends
        on the directory the suite runs from, and is not this test's subject.
        """
        with TestClient(Application(ApplicationContainer().build()).asgi()) as started:
            body = started.get("/health").json()
        assert body["status"] == "ok"
        assert isinstance(body["database_configured"], bool)

    def test_response_carries_no_credentials(self, client: TestClient) -> None:
        """A password reaching a health endpoint is a disclosure."""
        body = client.get("/health").text
        assert "never-in-a-response" not in body
        assert "tutor_owner" not in body


class TestApplicationWiring:
    def test_openapi_documents_the_route(self, client: TestClient) -> None:
        assert "/health" in client.get("/openapi.json").json()["paths"]

    def test_the_injected_parameter_is_not_asked_of_the_caller(
        self, client: TestClient
    ) -> None:
        """Depends() must not surface as a query parameter."""
        schema = client.get("/openapi.json").json()
        parameters = schema["paths"]["/health"]["get"].get("parameters", [])
        assert [p["name"] for p in parameters] == []

    def test_settings_is_an_annotated_fastapi_dependency(self) -> None:
        route = next(
            route
            for route in HealthRouter().router().routes
            if isinstance(route, APIRoute)
        )
        assert [dependency.name for dependency in route.dependant.dependencies] == [
            "settings"
        ]
        annotation = get_type_hints(route.endpoint, include_extras=True)["settings"]
        assert get_origin(annotation) is Annotated
        dependency_type, *metadata = get_args(annotation)
        assert dependency_type is ApplicationSettings
        depends = next(item for item in metadata if isinstance(item, Depends))
        assert isinstance(depends.dependency, Provide)

    def test_two_applications_do_not_share_a_container(self) -> None:
        """Per-app state: the unconfigured graph must not affect the real one."""
        with (
            _client(UnconfiguredSettingsProvider()) as first,
            _client(ConfiguredSettingsProvider()) as second,
        ):
            assert first.get("/health").json()["database_configured"] is False
            assert second.get("/health").json()["database_configured"] is True
