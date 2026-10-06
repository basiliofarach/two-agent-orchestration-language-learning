"""ASGI entrypoint. The object graph is built here and nowhere else."""

from collections.abc import Awaitable, Callable
from typing import cast

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from tutor_api.container import ApplicationContainer, SettingsProvider
from tutor_api.di.container import Container
from tutor_api.routers.errors import ProblemMapping
from tutor_api.routers.health import HealthRouter
from tutor_api.routers.reports import ReportRouter
from tutor_api.routers.sessions import (
    ActionRouter,
    AuditRouter,
    EventRouter,
    LearnerRouter,
    SessionRouter,
)
from tutor_api.routers.turns import TurnRouter
from tutor_api.settings import ApplicationSettings


class RequestScopeCloser:
    """Drop the request's scope after the response. Services have no dispose."""

    async def __call__(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Close the scope the dependencies opened, then return the response."""
        try:
            response = await call_next(request)
        finally:
            scope = getattr(request.state, "scope", None)
            if scope is not None:
                scope.close()
        return response


class Application:
    """Compose the container with FastAPI.

    The built container is injected rather than built here, so a test can
    register a different provider and hand in the same container the routes
    resolve from. Building it inside would leave no seam.
    """

    def __init__(self, container: Container) -> None:
        self._container = container

    def asgi(self) -> FastAPI:
        """Return the configured ASGI application."""
        app = FastAPI(
            title="Supervised two-agent language-learning tutor",
            description=(
                "Compliance-evidence prototype for EU AI Act "
                "Articles 10, 12, 14 and 15."
            ),
        )
        # Per-application state, not a global: `Provide` reads the container
        # back off the request, so two applications in one process — which the
        # test suite creates — never share a graph.
        app.state.container = self._container
        for router in (
            HealthRouter(),
            TurnRouter(),
            SessionRouter(),
            LearnerRouter(),
            AuditRouter(),
            ActionRouter(),
            EventRouter(),
            ReportRouter(),
        ):
            app.include_router(router.router())
        ProblemMapping().install(app)
        app.middleware("http")(RequestScopeCloser())
        # Registered last, so it wraps everything above and a refused
        # request still carries the CORS headers the browser needs to read it.
        settings = cast(
            ApplicationSettings, self._container.resolve(ApplicationSettings)
        )
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.allowed_origins()),
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "Last-Event-ID"],
        )
        return app


# The ASGI server imports a name, so the entrypoint is a module attribute. It
# is a constructed entrypoint, not global mutable state: nothing reassigns it,
# and every collaborator below it is injected.
app = Application(ApplicationContainer(SettingsProvider()).build()).asgi()
