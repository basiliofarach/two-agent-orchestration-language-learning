"""Liveness, and a statement that configuration resolved through the graph."""

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from tutor_api.settings import Settings


class HealthStatus(BaseModel):
    """What ``GET /health`` returns (DEC-0002)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: str
    database_configured: bool


class HealthRouter:
    """Class-based router: routes are bound methods, so no module-level
    function holds behaviour (rule 2).

    ``Settings`` arrives at the handler signature and nowhere else.
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
