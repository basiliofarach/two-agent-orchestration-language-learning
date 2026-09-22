"""Liveness, and a statement that configuration resolved through the graph."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from tutor_api.di.dependency import Provide
from tutor_api.settings import DatabaseSettings

# The annotated alias is the whole DI surface a handler sees: it asks for the
# type, and the container answers. `Provide` holds a type and nothing else, so
# this module-level name is a constant, not state.
Settings = Annotated[DatabaseSettings, Depends(Provide(DatabaseSettings))]


class HealthStatus(BaseModel):
    """What ``GET /health`` returns (DEC-0002)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: str
    database_configured: bool


class HealthRouter:
    """Class-based router: routes are bound methods, so no module-level
    function holds behaviour (rule 2).

    ``DatabaseSettings`` arrives at the handler signature and nowhere else.
    The handler never constructs it and never reads the environment: the
    container resolves it below the router and the signature is the seam
    (rule 3, DEC-0013).
    """

    def router(self) -> APIRouter:
        """Return this handler's routes, bound to this instance."""
        router = APIRouter(tags=["health"])
        router.add_api_route(
            "/health",
            self.read,
            methods=["GET"],
            response_model=HealthStatus,
        )
        return router

    async def read(self, settings: Settings) -> HealthStatus:
        """Report liveness and whether a database target is configured.

        The values are never returned. A password reaching a health endpoint
        is a disclosure, so this answers only whether configuration resolved.
        """
        return HealthStatus(
            status="ok",
            database_configured=bool(settings.database_url or settings.postgres_db),
        )
