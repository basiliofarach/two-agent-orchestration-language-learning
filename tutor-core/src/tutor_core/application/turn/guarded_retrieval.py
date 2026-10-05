"""Permission gate, then retrieval. A non-pass verdict does not retrieve."""

from abc import ABC, abstractmethod

from tutor_core.application.agents.retrieval import RetrievalAgent
from tutor_core.domain.models.learner import HistoryFieldSet
from tutor_core.domain.models.pipeline import GuardedRetrievalResult
from tutor_core.domain.models.retrieval import RedactedRetrievalRequest
from tutor_core.domain.models.turn import TurnState
from tutor_core.domain.ports.oversight_gate import OversightGatePort


class RetrievalGuard(ABC):
    """One graph point: permission, then retrieval. Not a DEC-0001 port.

    This is not a single-pass chain over a finished turn (DEC-0005). It
    is the edge the permission gate guards.
    """

    @abstractmethod
    async def run(self, turn: TurnState) -> GuardedRetrievalResult:
        """Evaluate permission. Retrieve only on ``pass``."""
        raise NotImplementedError  # pragma: no cover


class RetrieveIfPermitted(RetrievalGuard):
    """Call the retrieval agent only when the permission gate passes.

    The request and the history fields are read from the turn the gate
    judged, so retrieval cannot ask for more than was permitted.
    """

    def __init__(self, gate: OversightGatePort, agent: RetrievalAgent) -> None:
        self._gate = gate
        self._agent = agent

    async def run(self, turn: TurnState) -> GuardedRetrievalResult:
        """Stop or pause leaves the agent uncalled."""
        verdict = await self._gate.evaluate(turn)
        if verdict.decision != "pass":
            return GuardedRetrievalResult(verdict=verdict, context=None)
        prompt = turn.learner_prompt
        if prompt is None:
            msg = "a passing permission verdict has no prompt"
            raise ValueError(msg)
        requested = HistoryFieldSet.model_validate(
            {"fields": turn.requested_history_fields}
        )
        context = await self._agent.retrieve(
            RedactedRetrievalRequest(prompt=prompt),
            turn.learner_id,
            requested,
        )
        return GuardedRetrievalResult(verdict=verdict, context=context)
