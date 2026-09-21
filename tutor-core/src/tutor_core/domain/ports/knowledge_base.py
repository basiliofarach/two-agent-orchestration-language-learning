"""Retrieve from the vetted corpus only."""

from abc import ABC, abstractmethod

from tutor_core.domain.models.retrieval import RetrievalQuery, RetrievalResult


class KnowledgeBasePort(ABC):
    """Retrieve vetted educational material (REQ-KB, REQ-COMP).

    Scope boundary: the vetted corpus only. This port exposes no open-web,
    arbitrary-URL, or external-search method.
    """

    @abstractmethod
    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        """Return sourced snippets from the curated knowledge base."""
        raise NotImplementedError  # pragma: no cover
