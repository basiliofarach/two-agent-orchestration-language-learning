"""The four gates, in the only order REQ-GATES allows."""

from tutor_core.domain.models.audit import GATE_ORDER
from tutor_core.domain.models.verdict import GateStage
from tutor_core.domain.ports.oversight_gate import OversightGatePort


class GateRegistry:
    """Declare permission, conflict, sensitivity, then drift (REQ-GATES).

    The graph invokes each gate at its own node. This registry is the
    declaration those nodes are checked against, so a gate cannot be
    registered twice or out of order. It does not run the gates and it
    does not log: logging stays with the record the orchestrator builds
    (DEC-0005).
    """

    def __init__(self, gates: tuple[OversightGatePort, ...]) -> None:
        names = tuple(gate.name() for gate in gates)
        if names != GATE_ORDER:
            msg = "gates must be permission, conflict, sensitivity, then drift"
            raise ValueError(msg)
        self._gates = gates

    def ordered(self) -> tuple[OversightGatePort, ...]:
        """The four gates, in REQ-GATES order."""
        return self._gates

    def at(self, stage: GateStage) -> OversightGatePort:
        """The gate registered for ``stage``."""
        for gate in self._gates:
            if gate.name() == stage:
                return gate
        msg = f"no gate is registered for {stage}"
        raise KeyError(msg)
