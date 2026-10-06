"""ASGI entrypoint. The object graph is built here and nowhere else."""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import Response

from tutor_api.container import ApplicationContainer, SettingsProvider
from tutor_api.di.container import Container
from tutor_api.routers.health import HealthRouter
from tutor_api.routers.sessions import (
    ActionRouter,
    AuditRouter,
    EventRouter,
    SessionRouter,
)
from tutor_api.routers.turns import (
    SessionRejectionHandler,
    TurnFailureHandler,
    TurnRouter,
)
from tutor_core.application.services.conduct_turn import TurnFailed
from tutor_core.domain.ports.human_action import ActionRejected
from tutor_core.domain.ports.tutoring_session import SessionRejected


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
        app.include_router(HealthRouter().router())
        app.include_router(TurnRouter().router())
        app.include_router(SessionRouter().router())
        app.include_router(AuditRouter().router())
        app.include_router(ActionRouter().router())
        app.include_router(EventRouter().router())
        app.add_exception_handler(TurnFailed, TurnFailureHandler())
        app.add_exception_handler(SessionRejected, SessionRejectionHandler())
        app.add_exception_handler(ActionRejected, SessionRejectionHandler())
        app.middleware("http")(RequestScopeCloser())
        return app


# The ASGI server imports a name, so the entrypoint is a module attribute. It
# is a constructed entrypoint, not global mutable state: nothing reassigns it,
# and every collaborator below it is injected.
app = Application(ApplicationContainer(SettingsProvider()).build()).asgi()
