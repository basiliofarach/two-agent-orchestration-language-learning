"""The run label and licence status Article 15 reports (REQ-SIM)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tutor_api.evidence.body import PackBody
from tutor_core.domain.ports.simulation_report import SimulationReportPort


class RunLabel(BaseModel):
    """What the latest finished run says about itself, from its two files.

    ``field_label`` is read from ``summary.json`` and ``rubric_label`` from
    ``report.json``. The pack refuses a pair that disagree, so the label
    check compares two files the harness wrote rather than a default with
    itself.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_label: str = Field(min_length=1)
    rubric_label: str = Field(min_length=1)
    licence_status: Literal["confirmed", "pending", "not_in_this_pack"]
    pending_sources: tuple[str, ...] = ()


class LatestSimulationRun:
    """Read the most recently finished run through the read-only port.

    With no finished run the pack keeps ``simulated:unreleased`` and says
    the licence status is not in this pack. A run that is listed but whose
    report cannot be read stops the pack: an Article 15 page that guessed
    the licence status would be worse than none.
    """

    _UNRELEASED = "simulated:unreleased"

    def __init__(self, reports: SimulationReportPort) -> None:
        self._reports = reports

    def label(self) -> RunLabel:
        """The label, licence status and pending sources to print."""
        finished = [
            summary
            for summary in self._reports.runs()
            if summary.complete and summary.finished_at is not None
        ]
        if not finished:
            return RunLabel(
                field_label=self._UNRELEASED,
                rubric_label=self._UNRELEASED,
                licence_status="not_in_this_pack",
            )
        latest = max(
            finished, key=lambda summary: (summary.finished_at, summary.run_id)
        )
        report = self._reports.report(latest.run_id)
        return RunLabel(
            field_label=latest.label,
            rubric_label=report.label,
            licence_status=report.licence_status,
            pending_sources=report.pending_sources,
        )

    def applied(self, body: PackBody, label: RunLabel) -> PackBody:
        """The body with the run's label, re-validated so the pattern holds."""
        return PackBody.model_validate(
            {
                **body.model_dump(),
                "rubric_label": label.rubric_label,
                "licence_status": label.licence_status,
                "pending_sources": label.pending_sources,
            }
        )
