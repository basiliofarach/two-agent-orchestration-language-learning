"""Submit one learner question, read a recorded turn, or replay it (DEC-0011)."""

from uuid import UUID

from fastapi import APIRouter

from tutor_api.routers.deps import Replays, TurnReads, Turns
from tutor_api.routers.errors import ProblemMapping
from tutor_core.application.services.read_audit import TurnAuditCommand, TurnDetail
from tutor_core.application.services.replay_turn import ReplayCommand, ReplayReport
from tutor_core.domain.models.conduct import TurnCommand, TurnOutcome


class TurnRouter:
    """Class-based router. Each handler walks the chain and holds no logic.

    ``prepare``, ``execute`` and ``finalise`` are three calls on three types;
    the handler never calls a stage handler's ``run`` (DEC-0011).
    """

    def router(self) -> APIRouter:
        """Return this handler's routes, bound to this instance."""
        problems = ProblemMapping()
        router = APIRouter(tags=["turns"])
        router.add_api_route(
            "/turns",
            self.conduct,
            methods=["POST"],
            response_model=TurnOutcome,
            responses=problems.responses(422, 503),
        )
        router.add_api_route(
            "/turns/{turn_id}",
            self.read,
            methods=["GET"],
            response_model=TurnDetail,
            responses=problems.responses(404, 409),
        )
        router.add_api_route(
            "/turns/{turn_id}/replay",
            self.replay,
            methods=["POST"],
            response_model=ReplayReport,
            responses=problems.responses(404),
        )
        return router

    async def conduct(self, body: TurnCommand, service: Turns) -> TurnOutcome:
        """Run one turn through the four gates and return it to the tutor."""
        return (await service.prepare(body).execute()).finalise()

    async def read(self, turn_id: UUID, service: TurnReads) -> TurnDetail:
        """Return one recorded turn with its actions and the chunks it cited."""
        command = TurnAuditCommand(turn_id=turn_id)
        return (await service.prepare(command).execute()).finalise()

    async def replay(self, turn_id: UUID, service: Replays) -> ReplayReport:
        """Generate the turn again from its record and report what matched."""
        command = ReplayCommand(turn_id=turn_id)
        return (await service.prepare(command).execute()).finalise()
