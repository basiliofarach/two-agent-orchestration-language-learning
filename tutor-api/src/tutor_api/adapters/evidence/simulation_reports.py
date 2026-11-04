"""Read ``summary.json`` and ``report.json`` from the evidence directory."""

from pathlib import Path

from pydantic import ValidationError

from tutor_core.domain.models.simulation import SimulationReport, SimulationRunSummary
from tutor_core.domain.ports.simulation_report import (
    ReportMissing,
    ReportUnreadable,
    SimulationReportPort,
)


class EvidenceDirectoryReports(SimulationReportPort):
    """One subdirectory per run. A path outside the root is refused."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def runs(self) -> tuple[SimulationRunSummary, ...]:
        """List every summary, finished or not."""
        if not self._root.is_dir():
            return ()
        found: list[SimulationRunSummary] = []
        for child in sorted(path for path in self._root.iterdir() if path.is_dir()):
            summary = child / "summary.json"
            if not summary.is_file():
                continue
            found.append(self._summary(child.name, summary))
        return tuple(found)

    def report(self, run_id: str) -> SimulationReport:
        """Read C3. A missing file and a file that fails validation differ."""
        path = self._inside(run_id) / "report.json"
        if not path.is_file():
            raise ReportMissing(run_id)
        try:
            loaded = path.read_text(encoding="utf-8")
            return SimulationReport.model_validate_json(loaded)
        except ValidationError as exc:
            raise ReportUnreadable(run_id) from exc

    def _summary(self, directory: str, path: Path) -> SimulationRunSummary:
        try:
            summary = SimulationRunSummary.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except ValidationError as exc:
            raise ReportUnreadable(directory) from exc
        if summary.run_id != directory:
            raise ReportUnreadable(directory)
        return summary

    def _inside(self, run_id: str) -> Path:
        if not run_id or run_id in {".", ".."} or "/" in run_id or "\\" in run_id:
            raise ReportMissing(run_id)
        root = self._root.resolve()
        path = (root / run_id).resolve()
        if not path.is_relative_to(root):
            raise ReportMissing(run_id)
        return path
