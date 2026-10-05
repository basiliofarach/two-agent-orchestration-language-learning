"""Verify claims against retrieved sources. Unsupported spans stay."""

from abc import ABC, abstractmethod

from tutor_core.domain.models.retrieval import Snippet
from tutor_core.domain.models.safety import SourceSupportReport


class SourceSupportPort(ABC):
    """Verify claims against retrieved sources (REQ-COMP, REQ-ACCURACY).

    Scope boundary: flag unsupported spans for human review. This port must
    not remove them. ``snippets`` carry the passage text; a source
    reference alone has no passage to check a claim against.
    """

    @abstractmethod
    def verify(
        self,
        draft: str,
        snippets: tuple[Snippet, ...],
    ) -> SourceSupportReport:
        """Return supported and unsupported spans for ``draft``."""
        raise NotImplementedError  # pragma: no cover
