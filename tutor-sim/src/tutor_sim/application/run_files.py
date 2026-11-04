"""One directory per run under ``evidence/runs`` (contracts C3 and C4)."""

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from tutor_sim.domain.models.report import RunSummary, SimulationReport


class RunDirectory:
    """Write ``report.json``, then ``summary.json``, each by atomic rename.

    The API lists a run by its summary and serves its report, so the
    summary goes last: a listed run always has a report to read. A reader
    never sees a half-written file, because each lands under its own name
    only once it is complete.
    """

    def __init__(self, evidence: Path) -> None:
        self._root = evidence / "runs"

    def path(self, run_id: str) -> Path:
        """The run's directory."""
        return self._root / run_id

    def write(
        self,
        report: SimulationReport,
        tier: Literal["1", "2"],
        finished_at: datetime,
    ) -> Path:
        """Write both files for a finished run and return the directory."""
        directory = self.path(report.run_id)
        directory.mkdir(parents=True, exist_ok=True)
        summary = RunSummary(
            run_id=report.run_id,
            dataset_version=report.dataset_version,
            tier=tier,
            finished_at=finished_at,
            label=report.label,
            passed_invariants=report.finished,
            licence_status=report.licence_status,
            complete=True,
        )
        self._replace(directory / "report.json", report)
        self._replace(directory / "summary.json", summary)
        return directory

    def _replace(self, destination: Path, record: BaseModel) -> None:
        partial = destination.with_name(f".{destination.name}.partial")
        partial.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        partial.replace(destination)
