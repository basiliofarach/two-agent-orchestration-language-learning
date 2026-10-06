"""Sensitivity and drift gates, after generation. Each path, and no mutation."""

import inspect

import pytest
from tests.contract.test_port_contracts import OversightGatePortContract
from tests.support.gate_card import BrokenPolicy, CardPolicy, GateCard, GateRules
from tests.support.samples import Samples

from tutor_api.prototype import PrototypeCopy
from tutor_core.domain.gates.citation import VerdictCitation
from tutor_core.domain.gates.drift import DriftAnomalyGate
from tutor_core.domain.gates.sensitivity import SensitivityHighStakesGate
from tutor_core.domain.models.gate_rules import DriftEnvelope, SessionEnvelope
from tutor_core.domain.models.session_baseline import SessionBaseline
from tutor_core.domain.models.turn import TurnState
from tutor_core.domain.policy.rule_lookup import PolicyRuleLookup
from tutor_core.domain.ports.oversight_gate import OversightGatePort
from tutor_core.domain.ports.policy_artifact import PolicyArtifactPort


class OutputGates:
    """The two post-generation gates over the prototype card."""

    def sensitivity(
        self,
        policy: PolicyArtifactPort | None = None,
        flagged: tuple[str, ...] = ("proficiency", "unsafe"),
    ) -> SensitivityHighStakesGate:
        return SensitivityHighStakesGate(
            policy if policy is not None else CardPolicy(GateCard().build()),
            flagged,
            GateRules().sensitivity(),
            VerdictCitation(PolicyRuleLookup()),
        )

    def drift(
        self,
        policy: PolicyArtifactPort | None = None,
        envelope: DriftEnvelope | None = None,
        session: SessionEnvelope | None = None,
    ) -> DriftAnomalyGate:
        return DriftAnomalyGate(
            policy if policy is not None else CardPolicy(GateCard().build()),
            envelope if envelope is not None else self.loose(),
            session if session is not None else self.session(),
            GateRules().drift(),
            VerdictCitation(PolicyRuleLookup()),
        )

    def session(self) -> SessionEnvelope:
        return SessionEnvelope(
            min_prior_turns=2,
            max_support_drop=0.3,
            max_length_factor=3.0,
            max_flagged_prompts=2,
        )

    def in_session(self, **baseline: object) -> TurnState:
        """The sample turn, after earlier turns summarised by ``baseline``."""
        turn = Samples().turn()
        turn.session_baseline = SessionBaseline.model_validate(
            {
                "prior_turns": 3,
                "generated_turns": 3,
                "mean_support_ratio": 0.5,
                "mean_output_characters": 17.0,
                "flagged_prompts": 0,
                **baseline,
            }
        )
        return turn

    def loose(self) -> DriftEnvelope:
        return DriftEnvelope(
            min_retrieval_confidence=0.0,
            min_support_ratio=0.0,
            max_output_characters=1000,
            max_grammar_findings=5,
        )

    def routine_turn(self) -> TurnState:
        turn = Samples().turn()
        turn.safety_flags = ()
        return turn


class TestSensitivityGateContract(OversightGatePortContract):
    def port(self) -> OversightGatePort:
        return OutputGates().sensitivity()


class TestDriftGateContract(OversightGatePortContract):
    def port(self) -> OversightGatePort:
        return OutputGates().drift()


class TestSensitivityHighStakesGate:
    async def test_sensitivity_gate_passes_routine_content(self) -> None:
        verdict = (
            await OutputGates().sensitivity().evaluate(OutputGates().routine_turn())
        )
        assert verdict.decision == "pass"
        assert verdict.policy_rule_id == GateRules().sensitivity().routine

    async def test_sensitivity_gate_pauses_when_proficiency_flagged(self) -> None:
        verdict = await OutputGates().sensitivity().evaluate(Samples().turn())
        assert verdict.decision == "pause"
        assert verdict.policy_rule_id == GateRules().sensitivity().flagged_category

    async def test_a_flag_outside_the_flagged_categories_passes(self) -> None:
        gate = OutputGates().sensitivity(flagged=("unsafe",))
        verdict = await gate.evaluate(Samples().turn())
        assert verdict.decision == "pass"

    async def test_sensitivity_gate_stops_on_a_refusal(self) -> None:
        turn = OutputGates().routine_turn()
        turn.generated = (
            Samples()
            .generated()
            .model_copy(update={"refused": True, "refusal_reason": "out of scope"})
        )
        verdict = await OutputGates().sensitivity().evaluate(turn)
        assert verdict.decision == "stop"
        assert verdict.policy_rule_id == GateRules().sensitivity().refused

    async def test_no_generated_unit_stops_citing_evaluation_failed(self) -> None:
        turn = Samples().turn()
        turn.generated = None
        verdict = await OutputGates().sensitivity().evaluate(turn)
        assert verdict.decision == "stop"
        assert verdict.policy_rule_id == GateRules().sensitivity().evaluation_failed

    async def test_an_unreadable_card_raises(self) -> None:
        with pytest.raises(RuntimeError, match="unreadable"):
            await OutputGates().sensitivity(BrokenPolicy()).evaluate(Samples().turn())

    async def test_sensitivity_gate_does_not_mutate_the_turn(self) -> None:
        turn = Samples().turn()
        before = turn.model_dump()
        await OutputGates().sensitivity().evaluate(turn)
        assert turn.model_dump() == before

    def test_no_flagged_category_is_refused_at_construction(self) -> None:
        with pytest.raises(ValueError, match="no flagged category"):
            OutputGates().sensitivity(flagged=())

    def test_the_gate_holds_no_classifier_and_no_sink(self) -> None:
        names = set(inspect.signature(SensitivityHighStakesGate).parameters)
        assert names == {"policy", "flagged_categories", "rules", "citation"}
        assert OutputGates().sensitivity().name() == "sensitivity_and_high_stakes"


class TestDriftAnomalyGate:
    async def test_drift_gate_passes_inside_the_envelope(self) -> None:
        verdict = await OutputGates().drift().evaluate(Samples().turn())
        assert verdict.decision == "pass"
        assert verdict.policy_rule_id == GateRules().drift().within_envelope

    @pytest.mark.parametrize(
        "update",
        [
            {"min_retrieval_confidence": 0.9},
            {"min_support_ratio": 0.9},
            {"max_output_characters": 3},
            {"max_grammar_findings": 0},
        ],
    )
    async def test_drift_gate_pauses_outside_each_bound(
        self, update: dict[str, object]
    ) -> None:
        envelope = OutputGates().loose().model_copy(update=update)
        verdict = (
            await OutputGates().drift(envelope=envelope).evaluate(Samples().turn())
        )
        assert verdict.decision == "pause"
        assert verdict.policy_rule_id == GateRules().drift().outside_envelope

    async def test_missing_generation_stops(self) -> None:
        turn = Samples().turn()
        turn.generated = None
        verdict = await OutputGates().drift().evaluate(turn)
        assert verdict.decision == "stop"
        assert verdict.policy_rule_id == GateRules().drift().evaluation_failed

    async def test_an_unreadable_card_raises(self) -> None:
        with pytest.raises(RuntimeError, match="unreadable"):
            await OutputGates().drift(BrokenPolicy()).evaluate(Samples().turn())

    async def test_drift_gate_does_not_mutate_the_turn(self) -> None:
        turn = Samples().turn()
        before = turn.model_dump()
        await OutputGates().drift().evaluate(turn)
        assert turn.model_dump() == before

    async def test_the_first_turn_of_a_session_is_judged_per_turn_only(
        self,
    ) -> None:
        verdict = await OutputGates().drift().evaluate(Samples().turn())
        assert verdict.decision == "pass"

    async def test_support_well_below_the_session_norm_pauses(self) -> None:
        turn = OutputGates().in_session(mean_support_ratio=1.0)
        verdict = await OutputGates().drift().evaluate(turn)
        assert verdict.decision == "pause"
        assert verdict.policy_rule_id == GateRules().drift().outside_session_envelope

    async def test_a_reply_far_longer_than_the_session_norm_pauses(self) -> None:
        turn = OutputGates().in_session(mean_output_characters=4.0)
        verdict = await OutputGates().drift().evaluate(turn)
        assert verdict.decision == "pause"
        assert verdict.policy_rule_id == GateRules().drift().outside_session_envelope

    async def test_repeated_flagged_prompts_pause_an_ordinary_turn(self) -> None:
        turn = OutputGates().in_session(flagged_prompts=2)
        verdict = await OutputGates().drift().evaluate(turn)
        assert verdict.decision == "pause"
        assert verdict.policy_rule_id == GateRules().drift().outside_session_envelope

    async def test_a_turn_in_line_with_its_session_passes(self) -> None:
        verdict = await OutputGates().drift().evaluate(OutputGates().in_session())
        assert verdict.decision == "pass"

    async def test_too_few_earlier_drafts_do_not_set_a_norm(self) -> None:
        turn = OutputGates().in_session(
            generated_turns=1, mean_support_ratio=1.0, mean_output_characters=1.0
        )
        verdict = await OutputGates().drift().evaluate(turn)
        assert verdict.decision == "pass"

    def test_the_prototype_envelope_is_a_valid_envelope(self) -> None:
        envelope = PrototypeCopy().drift_envelope()
        assert envelope.max_output_characters > 0
        assert OutputGates().drift().name() == "drift_and_anomaly"


class TestVerdictCitation:
    def test_a_rule_the_card_does_not_name_raises(self) -> None:
        with pytest.raises(ValueError, match="has no rule"):
            VerdictCitation(PolicyRuleLookup()).cite(
                "drift_and_anomaly",
                GateCard().build(),
                "pass",
                "no-such-rule",
                "reason",
            )
