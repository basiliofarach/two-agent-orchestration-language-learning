"""Read the simulation evidence directory (REQ-SIM)."""

from pydantic import BaseModel, ConfigDict

from tutor_core.application.services.service import (
    ApplicationService,
    ExecuteHandler,
    FinaliseHandler,
    PrepareHandler,
)
from tutor_core.domain.models.simulation import SimulationReport, SimulationRunSummary
from tutor_core.domain.ports.simulation_report import (
    ReportMissing,
    SimulationReportPort,
)


class SimulationQuery(BaseModel):
    """A list, or one run when ``run_id`` is set."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str | None = None


class SimulationRead(BaseModel):
    """Whichever the query asked for."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    runs: tuple[SimulationRunSummary, ...] = ()
    report: SimulationReport | None = None


class PrepareSimulationReports(PrepareHandler[SimulationQuery, SimulationQuery]):
    """The query is already a model."""

    def run(self, command: SimulationQuery) -> SimulationQuery:
        """Return the query."""
        return command


class ExecuteSimulationReports(ExecuteHandler[SimulationQuery, SimulationRead]):
    """Read the directory. A missing or invalid report is the port's refusal."""

    def __init__(self, reports: SimulationReportPort) -> None:
        self._reports = reports

    async def run(self, prepared: SimulationQuery) -> SimulationRead:
        """Return the list, or the one report."""
        if prepared.run_id is None:
            return SimulationRead(runs=self._reports.runs())
        return SimulationRead(report=self._reports.report(prepared.run_id))


class FinaliseSimulationList(
    FinaliseHandler[SimulationRead, tuple[SimulationRunSummary, ...]]
):
    """The list is the result."""

    def run(self, executed: SimulationRead) -> tuple[SimulationRunSummary, ...]:
        """Return every summary."""
        return executed.runs


class FinaliseSimulationReport(FinaliseHandler[SimulationRead, SimulationReport]):
    """The one report is the result. A read that found nothing is a 404."""

    def run(self, executed: SimulationRead) -> SimulationReport:
        """Return the report."""
        if executed.report is None:
            raise ReportMissing("the simulation report was not read")
        return executed.report


class ListSimulationReports(
    ApplicationService[
        SimulationQuery,
        SimulationQuery,
        SimulationRead,
        tuple[SimulationRunSummary, ...],
    ]
):
    """The list route. Adds no method (DEC-0011)."""


class ReadSimulationReports(
    ApplicationService[
        SimulationQuery, SimulationQuery, SimulationRead, SimulationReport
    ]
):
    """The run route. Adds no method (DEC-0011)."""
