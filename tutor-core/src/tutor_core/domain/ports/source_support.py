"""Verify claims against retrieved sources. Unsupported spans stay."""

from abc import ABC, abstractmethod

from tutor_core.domain.models.retrieval import SourceRef
from tutor_core.domain.models.safety import SourceSupportReport


class SourceSupportPort(ABC):
    """Verify claims against retrieved sources (REQ-COMP, REQ-ACCURACY).

    Scope boundary: flag unsupported spans for human review. This port must
    not remove them.
    """

    @abstractmethod
    def verify(
        self,
        draft: str,
        sources: tuple[SourceRef, ...],
    ) -> SourceSupportReport:
        """Return supported and unsupported spans for ``draft``."""
        raise NotImplementedError  # pragma: no cover
