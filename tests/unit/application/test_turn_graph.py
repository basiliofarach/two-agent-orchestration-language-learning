"""The LangGraph turn: each gate at its own node, a non-pass ends the graph."""

from datetime import UTC, datetime, timedelta

from tests.support.samples import Samples
from tests.support.turn_stubs import (
    Agents,
    CountingHistory,
    CountingKnowledge,
    RecordingModel,
    ScriptedGate,
)

from tutor_core.application.agents.retrieval import DataRetrievalAgent
from tutor_core.application.turn.guarded_generation import GenerateIfConsistent
from tutor_core.application.turn.guarded_retrieval import RetrieveIfPermitted
from tutor_core.application.turn.orchestrator import (
    LangGraphTurnOrchestrator,
    TurnNodes,
)
from tutor_core.application.turn.state import TurnGraphState
from tutor_core.domain.models.retrieval import (
    RedactedRetrievalRequest,
    RetrievalResult,
)
from tutor_core.domain.models.safety import ModelCompletion, RenderedPrompt
from tutor_core.domain.models.turn import TurnState
from tutor_core.domain.models.verdict import GateDecision
from tutor_core.domain.ports.clock import ClockPort


class Timeline:
    """The order in which the clock, retrieval and the model were reached."""

    def __init__(self) -> None:
        self.events: list[str] = []


class TimelineClock(ClockPort):
    """One second later on every read, and each read is on the timeline."""

    def __init__(self, timeline: Timeline) -> None:
        self._timeline = timeline

    def now(self) -> datetime:
        self._timeline.events.append("clock")
        return datetime(2026, 1, 1, tzinfo=UTC) + timedelta(
            seconds=len(self._timeline.events)
        )


class TimelineKnowledge(CountingKnowledge):
    def __init__(self, timeline: Timeline) -> None:
        super().__init__()
        self._timeline = timeline

    async def retrieve(self, request: RedactedRetrievalRequest) -> RetrievalResult:
        self._timeline.events.append("retrieval")
        return await super().retrieve(request)


class TimelineModel(RecordingModel):
    def __init__(self, timeline: Timeline) -> None:
        super().__init__()
        self._timeline = timeline

    async def complete(self, prompt: RenderedPrompt) -> ModelCompletion:
        self._timeline.events.append("model")
        return await super().complete(prompt)


class Graph:
    """The real graph over scripted gates and counting stages."""

    def __init__(
        self,
        permission: GateDecision = "pass",
        conflict: GateDecision = "pass",
        sensitivity: GateDecision = "pass",
        drift: GateDecision = "pass",
    ) -> None:
        self.timeline = Timeline()
        self.knowledge = TimelineKnowledge(self.timeline)
        self.history = CountingHistory()
        self.model = TimelineModel(self.timeline)
        self.permission = ScriptedGate(permission, "context_and_permission")
        self.conflict = ScriptedGate(conflict, "conflict_and_ambiguity")
        self.sensitivity = ScriptedGate(sensitivity, "sensitivity_and_high_stakes")
        self.drift = ScriptedGate(drift, "drift_and_anomaly")
        self.orchestrator = LangGraphTurnOrchestrator(
            TurnNodes(
                RetrieveIfPermitted(
                    self.permission, DataRetrievalAgent(self.knowledge, self.history)
                ),
                GenerateIfConsistent(
                    self.conflict, Agents().generation(model=self.model)
                ),
                self.sensitivity,
                self.drift,
                TimelineClock(self.timeline),
            )
        )

    def fresh_turn(self) -> TurnState:
        sample = Samples().turn()
        return TurnState(
            turn_id=sample.turn_id,
            session_id=sample.session_id,
            learner_id=sample.learner_id,
            learner_prompt=sample.learner_prompt,
            requested_history_fields=("proficiency_level",),
        )

    async def run(self) -> TurnGraphState:
        return await self.orchestrator.run(self.fresh_turn())


class Decisions:
    def of(self, state: TurnGraphState) -> list[str]:
        return [verdict.decision for verdict in state.verdicts]


class TestTurnGraph:
    async def test_all_four_gates_pass_in_requirement_order(self) -> None:
        graph = Graph()
        state = await graph.run()
        assert [verdict.gate_name for verdict in state.verdicts] == [
            "context_and_permission",
            "conflict_and_ambiguity",
            "sensitivity_and_high_stakes",
            "drift_and_anomaly",
        ]
        assert state.halted() is False
        assert state.draft is not None
        assert state.turn.retrieved == Samples().retrieval()
        assert state.turn.history == Samples().history()
        assert state.turn.generated == state.draft.unit
        assert graph.model.calls == 1

    async def test_permission_stop_means_retrieval_never_runs(self) -> None:
        graph = Graph(permission="stop")
        state = await graph.run()
        assert Decisions().of(state) == ["stop"]
        assert graph.knowledge.calls == 0
        assert graph.history.calls == 0
        assert graph.conflict.calls == 0
        assert state.turn.retrieved is None

    async def test_conflict_pause_means_the_model_is_never_called(self) -> None:
        graph = Graph(conflict="pause")
        state = await graph.run()
        assert Decisions().of(state) == ["pass", "pause"]
        assert graph.knowledge.calls == 1
        assert graph.model.calls == 0
        assert graph.sensitivity.calls == 0
        assert state.draft is None

    async def test_sensitivity_pause_skips_the_drift_gate(self) -> None:
        graph = Graph(sensitivity="pause")
        state = await graph.run()
        assert Decisions().of(state) == ["pass", "pass", "pause"]
        assert graph.drift.calls == 0
        assert state.halted() is True

    async def test_drift_pause_is_the_last_verdict(self) -> None:
        graph = Graph(drift="pause")
        state = await graph.run()
        assert Decisions().of(state) == ["pass", "pass", "pass", "pause"]

    async def test_each_gate_is_stamped_before_the_stage_it_guards(self) -> None:
        graph = Graph()
        state = await graph.run()
        assert graph.timeline.events == [
            "clock",
            "retrieval",
            "clock",
            "model",
            "clock",
            "clock",
        ]
        stamps = [verdict.evaluated_at for verdict in state.verdicts]
        assert None not in stamps
        assert stamps == sorted(stamps)

    async def test_a_halting_gate_is_stamped_and_nothing_after_it_runs(
        self,
    ) -> None:
        graph = Graph(permission="stop")
        state = await graph.run()
        assert graph.timeline.events == ["clock"]
        assert state.verdicts[0].evaluated_at is not None

    async def test_a_state_with_no_verdict_is_not_halted(self) -> None:
        assert TurnGraphState(turn=Graph().fresh_turn()).halted() is False
