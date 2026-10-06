"""Submit one learner question and receive the gated turn (DEC-0011)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from tutor_api.di.dependency import Provide
from tutor_core.application.services.conduct_turn import ConductTurn
from tutor_core.domain.models.conduct import TurnCommand, TurnOutcome

# A plain assignment, as for ``Settings``: FastAPI unwraps this alias.
Turns = Annotated[ConductTurn, Depends(Provide(ConductTurn))]


class TurnFailure(BaseModel):
    """What a failed turn returns. No learner text and no SQL (REQ-MINOR)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    detail: str


class TurnRouter:
    """Class-based router. The handler walks the chain and holds no logic.

    ``prepare``, ``execute`` and ``finalise`` are three calls on three types;
    the handler never calls a stage handler's ``run`` (DEC-0011).
    """

    def router(self) -> APIRouter:
        """Return this handler's routes, bound to this instance."""
        router = APIRouter(tags=["turns"])
        router.add_api_route(
            "/turns",
            self.conduct,
            methods=["POST"],
            response_model=TurnOutcome,
            responses={503: {"model": TurnFailure}},
        )
        return router

    async def conduct(self, body: TurnCommand, service: Turns) -> TurnOutcome:
        """Run one turn through the four gates and return it to the tutor."""
        return (await service.prepare(body).execute()).finalise()


class SessionRejectionHandler:
    """Map a rejected session to 422. Retrieval did not run; nothing was kept."""

    async def __call__(self, request: Request, exc: Exception) -> JSONResponse:
        """Return the refusal. The message names no other learner."""
        return JSONResponse(
            status_code=422,
            content=TurnFailure(detail=str(exc)).model_dump(),
        )


class TurnFailureHandler:
    """Map ``TurnFailed`` to 503. The turn rolled back; nothing was recorded."""

    async def __call__(self, request: Request, exc: Exception) -> JSONResponse:
        """Return the failure without its cause's text."""
        return JSONResponse(
            status_code=503,
            content=TurnFailure(detail=str(exc)).model_dump(),
        )
