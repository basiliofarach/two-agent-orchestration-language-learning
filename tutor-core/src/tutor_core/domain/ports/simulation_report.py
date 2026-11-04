"""Read simulation reports. No write method (REQ-SIM)."""

from abc import ABC, abstractmethod

from tutor_core.domain.models.simulation import SimulationReport, SimulationRunSummary


class ReportMissing(Exception):
    """The named run has no readable report file."""


class ReportUnreadable(Exception):
    """The report file is present and does not match contract C3."""


class SimulationReportPort(ABC):
    """The evidence directory. Read-only."""

    @abstractmethod
    def runs(self) -> tuple[SimulationRunSummary, ...]:
        """Every run directory, including one that has not finished."""
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    def report(self, run_id: str) -> SimulationReport:
        """The finished report. Missing and unreadable are different refusals."""
        raise NotImplementedError  # pragma: no cover
