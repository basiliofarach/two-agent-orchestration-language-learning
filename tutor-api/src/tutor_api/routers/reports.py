"""Counts for the periodic non-discrimination review (REQ-MINOR)."""

from fastapi import APIRouter

from tutor_api.routers.deps import Cohorts
from tutor_core.application.services.report_cohort import CohortCommand
from tutor_core.domain.models.cohort import CohortReport


class ReportRouter:
    """The cohort counts. There is no verdict field to return."""

    def router(self) -> APIRouter:
        """Return the report route."""
        router = APIRouter(tags=["reports"])
        router.add_api_route(
            "/reports/cohort",
            self.cohort,
            methods=["GET"],
            response_model=CohortReport,
        )
        return router

    async def cohort(self, service: Cohorts) -> CohortReport:
        """Return the gate-decision and refusal counts."""
        return (await service.prepare(CohortCommand()).execute()).finalise()
