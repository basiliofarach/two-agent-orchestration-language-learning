"""Conflict gate, then generation. A non-pass verdict does not call the model."""

from abc import ABC, abstractmethod

from tutor_core.application.agents.generation import GenerationAgent
from tutor_core.domain.models.pipeline import GuardedGenerationResult
from tutor_core.domain.models.turn import TurnState
from tutor_core.domain.ports.oversight_gate import OversightGatePort


class GenerationGuard(ABC):
    """One graph point: conflict, then generation. Not a DEC-0001 port.

    This is not a single-pass chain over a finished turn (DEC-0005). It
    is the edge the conflict gate guards.
    """

    @abstractmethod
    async def run(self, turn: TurnState) -> GuardedGenerationResult:
        """Evaluate the retrieval. Generate only on ``pass``."""
        raise NotImplementedError  # pragma: no cover


class GenerateIfConsistent(GenerationGuard):
    """Call the generation agent only when the conflict gate passes.

    The task is the redacted prompt on the turn; the context and history
    are what the retrieval node wrote there.
    """

    def __init__(self, gate: OversightGatePort, agent: GenerationAgent) -> None:
        self._gate = gate
        self._agent = agent

    async def run(self, turn: TurnState) -> GuardedGenerationResult:
        """Pause or stop leaves the model uncalled."""
        verdict = await self._gate.evaluate(turn)
        if verdict.decision != "pass":
            return GuardedGenerationResult(verdict=verdict, draft=None)
        prompt = turn.learner_prompt
        retrieved = turn.retrieved
        history = turn.history
        if prompt is None or retrieved is None or history is None:
            msg = "a passing conflict verdict has no prompt, retrieval or history"
            raise ValueError(msg)
        draft = await self._agent.generate(prompt.text, retrieved, history)
        return GuardedGenerationResult(verdict=verdict, draft=draft)
