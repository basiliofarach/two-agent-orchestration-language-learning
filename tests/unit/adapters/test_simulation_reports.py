"""The evidence directory: a missing report, a bad report, and a path escape."""

import json
from pathlib import Path

import pytest

from tutor_api.adapters.evidence.simulation_reports import EvidenceDirectoryReports
from tutor_core.application.services.read_simulation_reports import (
    ExecuteSimulationReports,
    FinaliseSimulationReports,
    PrepareSimulationReports,
    ReadSimulationReports,
    SimulationQuery,
)
from tutor_core.domain.ports.simulation_report import ReportMissing, ReportUnreadable


class Directory:
    def write(
        self,
        root: Path,
        run_id: str,
        summary: dict[str, object],
        report: dict[str, object] | None,
    ) -> None:
        """One run directory. ``report`` omitted means the run is unfinished."""
        directory = root / run_id
        directory.mkdir()
        (directory / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        if report is not None:
            (directory / "report.json").write_text(json.dumps(report), encoding="utf-8")


def _summary(run_id: str, complete: bool) -> dict[str, object]:
    return {
        "run_id": run_id,
        "dataset_version": "sim-dataset/1.0.0",
        "tier": "1",
        "finished_at": "2026-01-01T00:00:00Z" if complete else None,
        "label": "simulated:sim-dataset/1.0.0",
        "passed_invariants": complete,
        "licence_status": "pending",
        "complete": complete,
    }


def _report(run_id: str) -> dict[str, object]:
    return {
        "run_id": run_id,
        "dataset_version": "sim-dataset/1.0.0",
        "label": "simulated:sim-dataset/1.0.0",
        "licence_status": "pending",
        "pending_sources": ["grammar-profile"],
        "rates": [],
        "invariants": [{"invariant_id": "INV-8", "passed": True}],
        "finished": True,
    }


def _service(root: Path) -> ReadSimulationReports:
    return ReadSimulationReports(
        PrepareSimulationReports(),
        ExecuteSimulationReports(EvidenceDirectoryReports(root)),
        FinaliseSimulationReports(),
    )


class TestEvidenceDirectoryReports:
    def test_an_incomplete_run_is_listed_and_has_no_report(
        self, tmp_path: Path
    ) -> None:
        Directory().write(tmp_path, "run-open", _summary("run-open", False), None)
        reports = EvidenceDirectoryReports(tmp_path)
        listed = reports.runs()
        assert listed[0].complete is False
        assert listed[0].finished_at is None
        with pytest.raises(ReportMissing):
            reports.report("run-open")

    def test_a_finished_report_is_read(self, tmp_path: Path) -> None:
        Directory().write(tmp_path, "run-1", _summary("run-1", True), _report("run-1"))
        report = EvidenceDirectoryReports(tmp_path).report("run-1")
        assert report.licence_status == "pending"
        assert report.pending_sources == ("grammar-profile",)

    def test_a_report_that_fails_validation_is_unreadable(self, tmp_path: Path) -> None:
        Directory().write(
            tmp_path, "run-1", _summary("run-1", True), {"run_id": "run-1"}
        )
        with pytest.raises(ReportUnreadable):
            EvidenceDirectoryReports(tmp_path).report("run-1")

    def test_a_path_outside_the_directory_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ReportMissing):
            EvidenceDirectoryReports(tmp_path).report("../secret")

    async def test_the_service_returns_the_list_then_the_report(
        self, tmp_path: Path
    ) -> None:
        Directory().write(tmp_path, "run-1", _summary("run-1", True), _report("run-1"))
        service = _service(tmp_path)
        listed = (await service.prepare(SimulationQuery()).execute()).finalise()
        assert [item.run_id for item in listed.runs] == ["run-1"]
        one = (
            await service.prepare(SimulationQuery(run_id="run-1")).execute()
        ).finalise()
        assert one.report is not None
        assert one.report.run_id == "run-1"
