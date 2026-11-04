"""Article 15 takes its run label and licence status from the latest report."""

from datetime import UTC, datetime

import pytest

from tutor_api.adapters.frozen_clock import FrozenClock
from tutor_api.evidence.body import EvidenceSources, PackBody
from tutor_api.evidence.pack import EvidencePack
from tutor_api.evidence.simulation import LatestSimulationRun
from tutor_core.domain.models.simulation import SimulationReport, SimulationRunSummary
from tutor_core.domain.ports.simulation_report import (
    ReportMissing,
    SimulationReportPort,
)


class MemoryReports(SimulationReportPort):
    """Summaries and reports held in memory, keyed by run id."""

    def __init__(
        self,
        summaries: tuple[SimulationRunSummary, ...] = (),
        reports: tuple[SimulationReport, ...] = (),
    ) -> None:
        self._summaries = summaries
        self._reports = {report.run_id: report for report in reports}

    def runs(self) -> tuple[SimulationRunSummary, ...]:
        return self._summaries

    def report(self, run_id: str) -> SimulationReport:
        if run_id not in self._reports:
            raise ReportMissing(run_id)
        return self._reports[run_id]


def _summary(
    run_id: str, day: int | None, label: str = "simulated:sim-dataset/0.1.0"
) -> SimulationRunSummary:
    return SimulationRunSummary(
        run_id=run_id,
        dataset_version="sim-dataset/0.1.0",
        tier="1",
        finished_at=None if day is None else datetime(2026, 11, day, tzinfo=UTC),
        label=label,
        passed_invariants=True,
        licence_status="pending",
        complete=day is not None,
    )


def _report(run_id: str, pending: tuple[str, ...]) -> SimulationReport:
    return SimulationReport(
        run_id=run_id,
        dataset_version="sim-dataset/0.1.0",
        label="simulated:sim-dataset/0.1.0",
        licence_status="pending" if pending else "confirmed",
        pending_sources=pending,
        finished=True,
    )


def _sources(field_label: str) -> EvidenceSources:
    return EvidenceSources(
        commit="abc",
        lockfile_sha256="a" * 64,
        model_revision="b" * 64,
        runtime="3.12.0",
        policy_version="prototype-1",
        chain_status="intact",
        field_label=field_label,
    )


class TestLatestSimulationRun:
    def test_no_finished_run_keeps_the_unreleased_label(self) -> None:
        reports = MemoryReports((_summary("run-open", None),))
        label = LatestSimulationRun(reports).label()
        assert label.field_label == "simulated:unreleased"
        assert label.licence_status == "not_in_this_pack"
        assert label.pending_sources == ()

    def test_the_latest_finished_run_names_its_pending_sources(self) -> None:
        reports = MemoryReports(
            (
                _summary("run-old", 1),
                _summary("run-new", 3),
                _summary("run-open", None),
            ),
            (_report("run-old", ()), _report("run-new", ("grammar-profile",))),
        )
        run = LatestSimulationRun(reports)
        label = run.label()
        body = run.applied(PackBody.empty(), label)
        assert body.licence_status == "pending"
        assert body.pending_sources == ("grammar-profile",)
        article = EvidencePack(FrozenClock(datetime(2026, 11, 4, tzinfo=UTC))).files(
            _sources(label.field_label), body
        )["article-15.md"]
        assert "Licence status: pending." in article
        assert "Pending sources: grammar-profile." in article
        assert "Run label: simulated:sim-dataset/0.1.0." in article

    def test_a_summary_and_report_that_disagree_are_refused_by_the_pack(
        self,
    ) -> None:
        reports = MemoryReports(
            (_summary("run-1", 1, label="simulated:sim-dataset/9.9.9"),),
            (_report("run-1", ()),),
        )
        run = LatestSimulationRun(reports)
        label = run.label()
        body = run.applied(PackBody.empty(), label)
        with pytest.raises(ValueError, match="must match the rubric label"):
            EvidencePack(FrozenClock(datetime(2026, 11, 4, tzinfo=UTC))).files(
                _sources(label.field_label), body
            )

    def test_a_label_outside_the_simulated_namespace_is_refused(self) -> None:
        reports = MemoryReports(
            (_summary("run-1", 1, label="validated"),),
            (_report("run-1", ()).model_copy(update={"label": "validated"}),),
        )
        run = LatestSimulationRun(reports)
        with pytest.raises(ValueError, match="simulated:"):
            run.applied(PackBody.empty(), run.label())
