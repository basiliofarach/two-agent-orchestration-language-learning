"""Counts for the periodic non-discrimination review (REQ-MINOR)."""

from fastapi import APIRouter

from tutor_api.routers.deps import Cohorts, SimulationLists, SimulationReports
from tutor_core.application.services.read_simulation_reports import SimulationQuery
from tutor_core.application.services.report_cohort import CohortCommand
from tutor_core.domain.models.cohort import CohortReport
from tutor_core.domain.models.simulation import SimulationReport, SimulationRunSummary


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
        router.add_api_route(
            "/reports/simulation",
            self.simulation_runs,
            methods=["GET"],
            response_model=tuple[SimulationRunSummary, ...],
        )
        router.add_api_route(
            "/reports/simulation/{run_id}",
            self.simulation_report,
            methods=["GET"],
            response_model=SimulationReport,
        )
        return router

    async def cohort(self, service: Cohorts) -> CohortReport:
        """Return the gate-decision and refusal counts."""
        return (await service.prepare(CohortCommand()).execute()).finalise()

    async def simulation_runs(
        self, service: SimulationLists
    ) -> tuple[SimulationRunSummary, ...]:
        """Return every run summary, including one that has not finished."""
        return (await service.prepare(SimulationQuery()).execute()).finalise()

    async def simulation_report(
        self, run_id: str, service: SimulationReports
    ) -> SimulationReport:
        """Return one C3 report. A missing file is 404; a bad file is 409."""
        return (
            await service.prepare(SimulationQuery(run_id=run_id)).execute()
        ).finalise()
