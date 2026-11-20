"""Source support is flagged for the tutor; it does not pause a turn as drift.

Support counts a sentence only when a retrieved passage states it word for
word. The knowledge base holds graded example sentences, not explanations,
so every tutoring reply scored 0.0 and the drift gate held every turn
(DEC-0005, amended 2026-11-19). The prototype's envelopes now leave the
support ratio out of drift. An altered vetted sentence still pauses
(``test_altered_claims``), and so do the other drift bounds.
"""

from tests.support.gate_card import GateRules
from tests.support.samples import Samples
from tests.unit.domain.test_output_gates import OutputGates

from tutor_api.prototype import PrototypeCopy
from tutor_core.domain.models.safety import SourceSupportReport
from tutor_core.domain.models.session_baseline import SessionBaseline
from tutor_core.domain.models.turn import TurnState


def _unsupported(turn: TurnState) -> TurnState:
    assert turn.generated is not None
    turn.generated = turn.generated.model_copy(
        update={
            "support": SourceSupportReport(
                supported=(),
                unsupported=(Samples().unsupported_span(),),
                support_ratio=0.0,
            )
        }
    )
    return turn


def _prototype_gate():  # type: ignore[no-untyped-def]
    copy = PrototypeCopy()
    return OutputGates().drift(
        envelope=copy.drift_envelope(), session=copy.session_envelope()
    )


class TestPrototypeEnvelopes:
    def test_support_has_no_floor_and_no_session_drop(self) -> None:
        copy = PrototypeCopy()
        assert copy.drift_envelope().min_support_ratio == 0.0
        assert copy.session_envelope().max_support_drop == 1.0

    def test_the_other_bounds_are_unchanged(self) -> None:
        envelope = PrototypeCopy().drift_envelope()
        assert envelope.min_retrieval_confidence == 0.3
        assert envelope.max_output_characters == 1200
        assert envelope.max_grammar_findings == 3
        session = PrototypeCopy().session_envelope()
        assert session.max_length_factor == 3.0
        assert session.max_flagged_prompts == 2


class TestDriftUnderThePrototype:
    async def test_an_unsupported_reply_passes_drift(self) -> None:
        verdict = await _prototype_gate().evaluate(_unsupported(Samples().turn()))
        assert verdict.decision == "pass"

    async def test_an_unsupported_reply_in_a_supported_session_passes(self) -> None:
        turn = _unsupported(Samples().turn())
        turn.session_baseline = SessionBaseline(
            prior_turns=3,
            generated_turns=3,
            mean_support_ratio=1.0,
            mean_output_characters=17.0,
            flagged_prompts=0,
        )
        verdict = await _prototype_gate().evaluate(turn)
        assert verdict.decision == "pass"

    async def test_an_overlong_unsupported_reply_still_pauses(self) -> None:
        turn = _unsupported(Samples().turn())
        assert turn.generated is not None
        long = "word " * 300
        turn.generated = turn.generated.model_copy(
            update={"output_before_checks": long, "output_after_checks": long}
        )
        verdict = await _prototype_gate().evaluate(turn)
        assert verdict.decision == "pause"
        assert verdict.policy_rule_id == GateRules().drift().outside_envelope

    async def test_the_unsupported_span_stays_on_the_turn(self) -> None:
        turn = _unsupported(Samples().turn())
        await _prototype_gate().evaluate(turn)
        assert turn.generated is not None
        assert turn.generated.support.unsupported == (Samples().unsupported_span(),)
