"""The evidence directory: a missing report, a bad report, and a path escape."""

import json
from pathlib import Path

import pytest

from tutor_api.adapters.evidence.simulation_reports import EvidenceDirectoryReports
from tutor_core.application.services.read_simulation_reports import (
    ExecuteSimulationReports,
    FinaliseSimulationList,
    FinaliseSimulationReport,
    ListSimulationReports,
    PrepareSimulationReports,
    ReadSimulationReports,
    SimulationQuery,
)
from tutor_core.domain.models.simulation import RateRow
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


def _execute(root: Path) -> ExecuteSimulationReports:
    return ExecuteSimulationReports(EvidenceDirectoryReports(root))


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

    def test_a_half_written_summary_does_not_hide_the_other_runs(
        self, tmp_path: Path
    ) -> None:
        Directory().write(tmp_path, "run-a", _summary("run-a", True), _report("run-a"))
        (tmp_path / "run-b").mkdir()
        (tmp_path / "run-b" / "summary.json").write_text('{"run_id": "ru', "utf-8")
        listed = EvidenceDirectoryReports(tmp_path).runs()
        assert [item.run_id for item in listed] == ["run-a"]

    def test_a_summary_naming_another_run_is_not_listed(self, tmp_path: Path) -> None:
        Directory().write(tmp_path, "run-a", _summary("run-z", True), None)
        assert EvidenceDirectoryReports(tmp_path).runs() == ()

    def test_a_report_that_is_not_utf8_is_unreadable(self, tmp_path: Path) -> None:
        Directory().write(tmp_path, "run-1", _summary("run-1", True), None)
        (tmp_path / "run-1" / "report.json").write_bytes(b"\xff\xfe{")
        with pytest.raises(ReportUnreadable):
            EvidenceDirectoryReports(tmp_path).report("run-1")

    def test_a_report_filed_under_another_run_is_unreadable(
        self, tmp_path: Path
    ) -> None:
        Directory().write(tmp_path, "run-1", _summary("run-1", True), _report("run-2"))
        with pytest.raises(ReportUnreadable):
            EvidenceDirectoryReports(tmp_path).report("run-1")

    def test_a_directory_without_a_summary_is_not_a_run(self, tmp_path: Path) -> None:
        (tmp_path / "scratch").mkdir()
        assert EvidenceDirectoryReports(tmp_path).runs() == ()

    def test_a_run_linked_outside_the_directory_is_refused(
        self, tmp_path: Path
    ) -> None:
        outside = tmp_path / "outside"
        Directory().write(
            tmp_path, "outside", _summary("run-1", True), _report("run-1")
        )
        root = tmp_path / "runs"
        root.mkdir()
        (root / "run-1").symlink_to(outside, target_is_directory=True)
        with pytest.raises(ReportMissing):
            EvidenceDirectoryReports(root).report("run-1")

    def test_a_path_outside_the_directory_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ReportMissing):
            EvidenceDirectoryReports(tmp_path).report("../secret")

    async def test_the_service_returns_the_list_then_the_report(
        self, tmp_path: Path
    ) -> None:
        Directory().write(tmp_path, "run-1", _summary("run-1", True), _report("run-1"))
        execute = _execute(tmp_path)
        listed = (
            await ListSimulationReports(
                PrepareSimulationReports(), execute, FinaliseSimulationList()
            )
            .prepare(SimulationQuery())
            .execute()
        ).finalise()
        assert [item.run_id for item in listed] == ["run-1"]
        one = (
            await ReadSimulationReports(
                PrepareSimulationReports(), execute, FinaliseSimulationReport()
            )
            .prepare(SimulationQuery(run_id="run-1"))
            .execute()
        ).finalise()
        assert one.run_id == "run-1"


class TestReadReportModel:
    def test_a_count_above_its_cases_is_refused(self) -> None:
        with pytest.raises(ValueError, match="k cannot exceed n"):
            RateRow(name="outcome", k=3, n=2)

    def test_a_count_within_its_cases_is_kept(self) -> None:
        assert RateRow(name="outcome", k=2, n=2).k == 2
