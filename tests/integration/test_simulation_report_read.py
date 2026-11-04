"""ReadSimulationReports over a directory, the same chain the router calls."""

from pathlib import Path

from tests.unit.adapters.test_simulation_reports import Directory, _report, _summary

from tutor_api.adapters.evidence.simulation_reports import EvidenceDirectoryReports
from tutor_core.application.services.read_simulation_reports import (
    ExecuteSimulationReports,
    FinaliseSimulationReports,
    PrepareSimulationReports,
    ReadSimulationReports,
    SimulationQuery,
)


async def test_prepare_execute_finalise_reads_the_directory(tmp_path: Path) -> None:
    Directory().write(tmp_path, "run-1", _summary("run-1", True), _report("run-1"))
    service = ReadSimulationReports(
        PrepareSimulationReports(),
        ExecuteSimulationReports(EvidenceDirectoryReports(tmp_path)),
        FinaliseSimulationReports(),
    )
    read = (await service.prepare(SimulationQuery(run_id="run-1")).execute()).finalise()
    assert read.report is not None
    assert read.report.pending_sources == ("grammar-profile",)
