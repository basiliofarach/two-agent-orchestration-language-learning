"""Data Retrieval Agent. Vetted snippets and allowlisted history only."""

from abc import ABC, abstractmethod

from tutor_core.domain.models.learner import HistoryFieldSet, LearnerId
from tutor_core.domain.models.retrieval import (
    RedactedRetrievalRequest,
    RetrievedContext,
)
from tutor_core.domain.ports.knowledge_base import KnowledgeBasePort
from tutor_core.domain.ports.learner_history import LearnerHistoryPort


class RetrievalAgent(ABC):
    """Retrieve for one turn. Not a DEC-0001 port.

    The stage-handler ABCs protect use-case stages (DEC-0011). This ABC
    protects the retrieval capability the orchestrator calls: vetted
    knowledge and allowlisted history, and nothing else.
    """

    @abstractmethod
    async def retrieve(
        self,
        request: RedactedRetrievalRequest,
        learner_id: LearnerId,
        requested: HistoryFieldSet,
    ) -> RetrievedContext:
        """Return snippets and the requested history. Empty knowledge is valid."""
        raise NotImplementedError  # pragma: no cover


class DataRetrievalAgent(RetrievalAgent):
    """Parse nothing beyond the redacted request. Hold no model and no HTTP.

    History reads go through ``LearnerHistoryPort``, whose allowlist is
    fixed at the port's construction. The agent reads the fields the turn
    requested — the ones the permission gate judged — and no others. This
    agent does not call a gate; the graph calls the permission gate first
    (BE-21, REQ-GATES).
    """

    def __init__(
        self,
        knowledge: KnowledgeBasePort,
        history: LearnerHistoryPort,
    ) -> None:
        self._knowledge = knowledge
        self._history = history

    async def retrieve(
        self,
        request: RedactedRetrievalRequest,
        learner_id: LearnerId,
        requested: HistoryFieldSet,
    ) -> RetrievedContext:
        """Read the vetted corpus and exactly the requested history fields."""
        knowledge = await self._knowledge.retrieve(request)
        history = await self._history.read(learner_id, requested)
        return RetrievedContext(knowledge=knowledge, history=history)
