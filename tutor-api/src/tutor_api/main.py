"""ASGI entrypoint. The object graph is built here and nowhere else."""

from fastapi import FastAPI

from tutor_api.container import ApplicationContainer
from tutor_api.di.container import Container
from tutor_api.routers.health import HealthRouter


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
        return app


# The ASGI server imports a name, so the entrypoint is a module attribute. It
# is a constructed entrypoint, not global mutable state: nothing reassigns it,
# and every collaborator below it is injected.
app = Application(ApplicationContainer().build()).asgi()
