"""One oversight gate. It returns a verdict and does not write the turn."""

from abc import ABC, abstractmethod

from tutor_core.domain.models.turn import TurnState
from tutor_core.domain.models.verdict import GateVerdict


class OversightGatePort(ABC):
    """One oversight gate in the orchestration graph (REQ-GATES, DEC-0005).

    Scope boundary: ``name()`` and ``evaluate(turn) -> GateVerdict``. A gate
    returns a verdict and has no write path. It must not assign to the
    mutable ``TurnState`` it receives (DEC-0010). ``evaluate`` is async
    because a verdict's ``policy_rule_id`` is resolved from the policy card
    on the turn's connection (DEC-0014).
    """

    @abstractmethod
    def name(self) -> str:
        """Return the gate name recorded with the verdict."""
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    async def evaluate(self, turn: TurnState) -> GateVerdict:
        """Judge ``turn`` and return a verdict. Do not modify ``turn``."""
        raise NotImplementedError  # pragma: no cover
