"""The tutoring turn as a LangGraph state graph (DEC-0004, DEC-0005)."""

from abc import ABC, abstractmethod

from langgraph.graph import END, START, StateGraph

from tutor_core.application.turn.guarded_generation import GenerationGuard
from tutor_core.application.turn.guarded_retrieval import RetrievalGuard
from tutor_core.application.turn.state import TurnGraphState
from tutor_core.domain.models.turn import TurnState
from tutor_core.domain.ports.oversight_gate import OversightGatePort


class TurnOrchestrator(ABC):
    """Run one turn through the gates and agents. Not a DEC-0001 port.

    The ABC is the seam the execute stage holds, so that stage can be tested
    without LangGraph and the graph can be tested without a database.
    """

    @abstractmethod
    async def run(self, turn: TurnState) -> TurnGraphState:
        """Return the graph state after the last node that ran."""
        raise NotImplementedError  # pragma: no cover


class TurnNodes:
    """The graph's nodes and its one routing rule. Each node is thin.

    A node resolves nothing: it delegates to a guard or a gate it was given,
    writes the result onto the turn, and returns the fields it changed.
    Gates return verdicts; this class is what assigns to the turn
    (DEC-0010). Logging the verdicts is the execute stage's job, from the
    state this graph returns.
    """

    def __init__(
        self,
        retrieval: RetrievalGuard,
        generation: GenerationGuard,
        sensitivity: OversightGatePort,
        drift: OversightGatePort,
    ) -> None:
        self._retrieval = retrieval
        self._generation = generation
        self._sensitivity = sensitivity
        self._drift = drift

    async def permission_then_retrieval(
        self, state: TurnGraphState
    ) -> dict[str, object]:
        """Permission gate, then retrieval only on ``pass`` (REQ-GATES)."""
        result = await self._retrieval.run(state.turn)
        if result.context is not None:
            state.turn.retrieved = result.context.knowledge
            state.turn.history = result.context.history
        return {"turn": state.turn, "verdicts": (*state.verdicts, result.verdict)}

    async def conflict_then_generation(
        self, state: TurnGraphState
    ) -> dict[str, object]:
        """Conflict gate, then generation only on ``pass`` (REQ-GATES)."""
        result = await self._generation.run(state.turn)
        draft = result.draft
        if draft is not None:
            state.turn.generated = draft.unit
            state.turn.safety_flags = draft.safety_flags
        return {
            "turn": state.turn,
            "verdicts": (*state.verdicts, result.verdict),
            "draft": draft,
        }

    async def sensitivity(self, state: TurnGraphState) -> dict[str, object]:
        """Sensitivity gate, after generation."""
        verdict = await self._sensitivity.evaluate(state.turn)
        return {"verdicts": (*state.verdicts, verdict)}

    async def drift(self, state: TurnGraphState) -> dict[str, object]:
        """Drift gate, after generation."""
        verdict = await self._drift.evaluate(state.turn)
        return {"verdicts": (*state.verdicts, verdict)}

    def proceed(self, state: TurnGraphState) -> bool:
        """Continue only after a ``pass``. A pause or stop ends the graph."""
        return not state.halted()


class LangGraphTurnOrchestrator(TurnOrchestrator):
    """permission → retrieval → conflict → generation → sensitivity → drift.

    The order is the graph's edges, not a list a loop walks (DEC-0005). A
    conditional edge after every gate routes a non-pass verdict to the end,
    so no later stage runs: a permission ``stop`` means retrieval never
    runs, and a conflict ``pause`` means the model is never called. Human
    review starts from the held turn this returns.
    """

    def __init__(self, nodes: TurnNodes) -> None:
        graph = StateGraph(TurnGraphState)
        graph.add_node("permission_then_retrieval", nodes.permission_then_retrieval)
        graph.add_node("conflict_then_generation", nodes.conflict_then_generation)
        graph.add_node("sensitivity", nodes.sensitivity)
        graph.add_node("drift", nodes.drift)
        graph.add_edge(START, "permission_then_retrieval")
        graph.add_conditional_edges(
            "permission_then_retrieval",
            nodes.proceed,
            {True: "conflict_then_generation", False: END},
        )
        graph.add_conditional_edges(
            "conflict_then_generation",
            nodes.proceed,
            {True: "sensitivity", False: END},
        )
        graph.add_conditional_edges(
            "sensitivity",
            nodes.proceed,
            {True: "drift", False: END},
        )
        graph.add_edge("drift", END)
        self._compiled = graph.compile()

    async def run(self, turn: TurnState) -> TurnGraphState:
        """Invoke the compiled graph on one turn."""
        final = await self._compiled.ainvoke(TurnGraphState(turn=turn))
        return TurnGraphState.model_validate(final)
