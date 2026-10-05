"""Retrieve from the vetted corpus only."""

from abc import ABC, abstractmethod

from tutor_core.domain.models.retrieval import (
    RedactedRetrievalRequest,
    RetrievalResult,
)


class KnowledgeBasePort(ABC):
    """Retrieve vetted educational material (REQ-KB, REQ-COMP).

    Scope boundary: the vetted corpus only. This port exposes no open-web,
    arbitrary-URL, or external-search method. It takes a redacted request,
    so raw learner text has no way in (REQ-MINOR). Async because it reads
    on the turn's enlisted connection (DEC-0014).
    """

    @abstractmethod
    async def retrieve(self, request: RedactedRetrievalRequest) -> RetrievalResult:
        """Return sourced snippets from the curated knowledge base."""
        raise NotImplementedError  # pragma: no cover
