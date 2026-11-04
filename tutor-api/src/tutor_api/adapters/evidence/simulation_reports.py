"""Read ``summary.json`` and ``report.json`` from the run directories."""

from pathlib import Path

from pydantic import ValidationError

from tutor_core.domain.models.simulation import SimulationReport, SimulationRunSummary
from tutor_core.domain.ports.simulation_report import (
    ReportMissing,
    ReportUnreadable,
    SimulationReportPort,
)


class EvidenceDirectoryReports(SimulationReportPort):
    """One subdirectory per run, as ``tutor_sim report`` writes them.

    ``root`` is ``evidence/runs``. A path outside it is refused. The list
    is an index: a summary that cannot be read, or that names a different
    run than its directory, is left out of it rather than hiding every
    other run behind one 409. That run's report is still asked for by id,
    and is refused there as unreadable or missing.
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    def runs(self) -> tuple[SimulationRunSummary, ...]:
        """List every readable summary, finished or not."""
        if not self._root.is_dir():
            return ()
        found: list[SimulationRunSummary] = []
        for child in sorted(path for path in self._root.iterdir() if path.is_dir()):
            summary = child / "summary.json"
            if not summary.is_file():
                continue
            try:
                found.append(self._summary(child.name, summary))
            except ReportUnreadable:
                continue
        return tuple(found)

    def report(self, run_id: str) -> SimulationReport:
        """Read C3. A missing file and a file that fails validation differ."""
        path = self._inside(run_id) / "report.json"
        if not path.is_file():
            raise ReportMissing(run_id)
        try:
            report = SimulationReport.model_validate_json(self._text(run_id, path))
        except ValidationError as exc:
            raise ReportUnreadable(run_id) from exc
        if report.run_id != run_id:
            raise ReportUnreadable(run_id)
        return report

    def _summary(self, directory: str, path: Path) -> SimulationRunSummary:
        try:
            summary = SimulationRunSummary.model_validate_json(
                self._text(directory, path)
            )
        except ValidationError as exc:
            raise ReportUnreadable(directory) from exc
        if summary.run_id != directory:
            raise ReportUnreadable(directory)
        return summary

    def _text(self, run_id: str, path: Path) -> str:
        """The file's text. Bytes that are not UTF-8 are a bad file, not a 500."""
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ReportUnreadable(run_id) from exc

    def _inside(self, run_id: str) -> Path:
        if not run_id or run_id in {".", ".."} or "/" in run_id or "\\" in run_id:
            raise ReportMissing(run_id)
        root = self._root.resolve()
        path = (root / run_id).resolve()
        if not path.is_relative_to(root):
            raise ReportMissing(run_id)
        return path
