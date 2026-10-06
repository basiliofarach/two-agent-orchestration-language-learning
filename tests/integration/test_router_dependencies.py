"""A route reaches a use case, never a stage handler or a port (DEC-0011).

The typestate chain stops ``execute`` being called before ``prepare`` only if
a route holds the ``ApplicationService`` and nothing below it. The handlers
are registered in the container, so ``Provide(ExecuteTurn)`` would resolve.
This walks every route of the composed application and fails on any
dependency that is not a use case or the settings.
"""

from collections.abc import Iterator, Sequence

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from starlette.routing import BaseRoute

from tutor_api.container import ApplicationContainer, SettingsProvider
from tutor_api.di.dependency import Provide
from tutor_api.main import Application
from tutor_api.settings import ApplicationSettings
from tutor_core.application.services.service import ApplicationService


class RouteDependencies:
    """Every type a route of the real application resolves through ``Provide``."""

    def resolved(self) -> Iterator[tuple[str, type]]:
        app = Application(ApplicationContainer(SettingsProvider()).build()).asgi()
        for route in self._routes(app.routes):
            for requested in self._walk(route.dependant):
                yield route.path, requested

    def _routes(self, routes: Sequence[BaseRoute]) -> Iterator[APIRoute]:
        # FastAPI 0.141 keeps an included router behind a wrapper that holds
        # the router it was given; earlier versions copied its routes.
        for route in routes:
            if isinstance(route, APIRoute):
                yield route
            included = getattr(route, "original_router", None)
            if included is not None:
                yield from self._routes(included.routes)

    def _walk(self, dependant: Dependant) -> Iterator[type]:
        for child in dependant.dependencies:
            if isinstance(child.call, Provide):
                yield child.call._requested  # noqa: SLF001 — the type it resolves
            yield from self._walk(child)


class TestRouteDependencies:
    def test_every_route_holds_a_use_case_or_the_settings(self) -> None:
        resolved = list(RouteDependencies().resolved())
        assert resolved, "the application declares routes with dependencies"
        offending = [
            (path, requested.__name__)
            for path, requested in resolved
            if not (
                issubclass(requested, ApplicationService)
                or requested is ApplicationSettings
            )
        ]
        assert offending == []

    def test_the_turn_route_holds_the_conduct_turn_service(self) -> None:
        paths = {
            path: requested.__name__
            for path, requested in RouteDependencies().resolved()
        }
        assert paths["/turns"] == "ConductTurn"
