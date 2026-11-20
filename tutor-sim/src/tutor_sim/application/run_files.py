"""One directory per run under ``evidence/runs`` (contracts C3 and C4)."""

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from tutor_sim.domain.models.observation import Tier1Pointer
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

    def claim(self, base: str) -> str:
        """Create the first free directory for ``base`` and return its id.

        A run never reuses a directory, so an earlier run's trail is kept.
        """
        self._root.mkdir(parents=True, exist_ok=True)
        candidate = base
        number = 1
        while True:
            try:
                self.path(candidate).mkdir()
            except FileExistsError:
                number += 1
                candidate = f"{base}-{number}"
                continue
            return candidate

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


class LatestTier1Run:
    """``evidence/tier1-latest.json``: the run ``report`` scores by default."""

    _NAME = "tier1-latest.json"

    def __init__(self, evidence: Path) -> None:
        self._path = evidence / self._NAME

    def point(self, run_id: str) -> None:
        """Move the pointer, by atomic rename, once a run has finished."""
        record = Tier1Pointer(run_id=run_id)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        partial = self._path.with_name(f".{self._NAME}.partial")
        partial.write_text(record.model_dump_json(), encoding="utf-8")
        partial.replace(self._path)

    def run_id(self) -> str | None:
        """``None`` until a Tier 1 run has finished."""
        if not self._path.is_file():
            return None
        text = self._path.read_text(encoding="utf-8")
        return Tier1Pointer.model_validate_json(text).run_id
