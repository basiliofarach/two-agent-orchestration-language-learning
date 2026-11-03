"""Fetch a pinned source. The harness holds no tutor-API client."""

from abc import ABC, abstractmethod

from tutor_sim.domain.models.source import SourceRecord


class SourceFetchPort(ABC):
    """Return the bytes of one source after its digest matches."""

    @abstractmethod
    def fetch(self, source: SourceRecord) -> bytes:
        """Return the artefact. A digest mismatch is fatal."""
        raise NotImplementedError  # pragma: no cover
