"""Aggregate the audit log for a periodic human review."""

from abc import ABC, abstractmethod

from tutor_core.domain.models.cohort import CohortReport


class CohortReportPort(ABC):
    """Counts over the audit log for the non-discrimination review (REQ-MINOR).

    Scope boundary: read-only aggregates. The port returns counts and no
    row-level data, and it has no method that classifies a result as fair
    or biased: the review is a person's (ARCHITECTURE §10).
    """

    @abstractmethod
    async def report(self) -> CohortReport:
        """Return the counts."""
        raise NotImplementedError  # pragma: no cover
