"""ReadSimulationReports over a directory, the same chain the router calls."""

from datetime import UTC, datetime
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
from tutor_sim.application.run_files import RunDirectory
from tutor_sim.domain.models.report import InvariantRow, SimulationReport


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


async def test_the_api_lists_and_reads_the_run_tutor_sim_wrote(tmp_path: Path) -> None:
    written = SimulationReport(
        run_id="run-20261104T120000",
        dataset_version="sim-dataset/0.1.0",
        label="simulated:sim-dataset/0.1.0",
        licence_status="pending",
        pending_sources=("grammar-profile",),
        invariants=(InvariantRow(invariant_id="INV-8", passed=True),),
        finished=True,
    )
    RunDirectory(tmp_path).write(written, "1", datetime(2026, 11, 4, 12, tzinfo=UTC))
    service = ReadSimulationReports(
        PrepareSimulationReports(),
        ExecuteSimulationReports(EvidenceDirectoryReports(tmp_path / "runs")),
        FinaliseSimulationReports(),
    )
    listed = (await service.prepare(SimulationQuery()).execute()).finalise()
    assert [run.run_id for run in listed.runs] == [written.run_id]
    assert listed.runs[0].complete is True
    assert listed.runs[0].licence_status == "pending"
    read = (
        await service.prepare(SimulationQuery(run_id=written.run_id)).execute()
    ).finalise()
    assert read.report is not None
    assert read.report.pending_sources == ("grammar-profile",)
