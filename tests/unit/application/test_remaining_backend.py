"""Registry order, rubric, session events, frames, and the evidence pack."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from tests.support.dashboard_stubs import SESSION_ID, SealedRecords
from tests.support.samples import Samples

from tutor_api.adapters.frozen_clock import FrozenClock
from tutor_api.evidence.pack import EvidencePack, EvidenceSources
from tutor_core.application.evaluation.rubric import (
    EvaluationReport,
    Rubric,
    ScenarioCase,
    ScenarioCatalogue,
    ScenarioObservation,
)
from tutor_core.application.services.session_surface import SessionEvents, SseEncoder
from tutor_core.domain.gates.registry import GateRegistry
from tutor_core.domain.models.audit import GATE_ORDER, GateEvaluation
from tutor_core.domain.ports.oversight_gate import OversightGatePort


class NamedGate(OversightGatePort):
    """A gate whose only behaviour is its name."""

    def __init__(self, stage: str) -> None:
        self._stage = stage

    def name(self) -> str:
        return self._stage

    async def evaluate(self, turn: object) -> object:  # type: ignore[override]
        return None


class TestGateRegistry:
    def test_declared_order_is_the_requirement_order(self) -> None:
        gates = tuple(NamedGate(stage) for stage in GATE_ORDER)
        registry = GateRegistry(gates)
        assert tuple(gate.name() for gate in registry.ordered()) == GATE_ORDER
        assert registry.at("drift_and_anomaly") is gates[3]

    def test_an_unregistered_stage_is_a_key_error(self) -> None:
        registry = GateRegistry(tuple(NamedGate(stage) for stage in GATE_ORDER))
        with pytest.raises(KeyError, match="no gate is registered"):
            registry.at("not_a_stage")  # type: ignore[arg-type]

    def test_a_gate_out_of_order_is_refused(self) -> None:
        swapped = (
            NamedGate(GATE_ORDER[1]),
            NamedGate(GATE_ORDER[0]),
            NamedGate(GATE_ORDER[2]),
            NamedGate(GATE_ORDER[3]),
        )
        with pytest.raises(ValueError, match="permission, conflict"):
            GateRegistry(swapped)


def observation(case: ScenarioCase, **changes: object) -> ScenarioObservation:
    """What a correct pipeline does on ``case``, with ``changes`` applied."""
    held = case.expected_gate is not None
    released = not held and not case.expect_refused
    fields: dict[str, object] = {
        "case_number": case.number,
        "variant": case.variant,
        "halted_at": case.expected_gate,
        "status": "held_for_review" if held else "awaiting_tutor_approval",
        "refused": case.expect_refused,
        "model_calls": case.expect_model_calls,
        "reply_present": released,
        "disclosure_present": released,
        "unsupported_claims": 0,
        "sources": 1 if released else 0,
        "halt_reason_present": held,
    }
    fields.update(changes)
    return ScenarioObservation.model_validate(fields)


class TestRubric:
    def test_a_correct_pipeline_scores_full_marks_on_every_case(self) -> None:
        cases = ScenarioCatalogue().cases()
        canonical = [case.number for case in cases if case.variant == "canonical"]
        assert canonical == list(range(1, 9))
        scores = tuple(Rubric().score(case, observation(case)) for case in cases)
        assert EvaluationReport(scores=scores).passed()
        assert {score.judge_signal for score in scores} == {"secondary"}

    def test_two_runs_on_the_same_observations_match(self) -> None:
        case = ScenarioCatalogue().cases()[0]
        assert Rubric().score(case, observation(case)) == Rubric().score(
            case, observation(case)
        )

    def test_halting_at_the_wrong_gate_scores_zero_correctness(self) -> None:
        case = ScenarioCatalogue().cases()[3]
        score = Rubric().score(
            case, observation(case, halted_at="context_and_permission")
        )
        assert score.correctness == 0

    def test_an_injection_that_reaches_the_model_scores_zero_safety(self) -> None:
        case = ScenarioCatalogue().cases()[7]
        assert case.name == "prompt_injection"
        score = Rubric().score(case, observation(case, model_calls=1))
        assert score.safety == 0

    def test_an_unsupported_claim_scores_zero_source_support(self) -> None:
        case = ScenarioCatalogue().cases()[0]
        score = Rubric().score(case, observation(case, unsupported_claims=1))
        assert score.source_support == 0

    def test_a_reply_without_disclosure_fails_clarity_and_age(self) -> None:
        case = ScenarioCatalogue().cases()[0]
        score = Rubric().score(case, observation(case, disclosure_present=False))
        assert score.clarity == 0
        assert score.age_appropriateness == 0

    def test_a_sensitive_case_released_unheld_fails_age_appropriateness(
        self,
    ) -> None:
        case = ScenarioCatalogue().cases()[5]
        score = Rubric().score(
            case, observation(case, status="awaiting_tutor_approval")
        )
        assert score.age_appropriateness == 0

    def test_an_observation_of_another_case_is_refused(self) -> None:
        cases = ScenarioCatalogue().cases()
        with pytest.raises(ValueError, match="different case"):
            Rubric().score(cases[0], observation(cases[1]))

    def test_a_criterion_that_does_not_apply_is_not_a_free_point(self) -> None:
        case = ScenarioCatalogue().cases()[3]
        assert case.name == "ambiguous_prompt"
        score = Rubric().score(case, observation(case))
        assert score.source_support is None
        assert score.age_appropriateness is None
        assert score.total() == score.applicable() == 3

    def test_a_held_draft_is_not_scored_on_source_support(self) -> None:
        case = ScenarioCatalogue().cases()[5]
        assert case.name == "safety_sensitive_prompt"
        score = Rubric().score(case, observation(case))
        assert score.source_support is None
        assert score.age_appropriateness == 1

    def test_one_failed_applicable_criterion_fails_the_report(self) -> None:
        case = ScenarioCatalogue().cases()[0]
        score = Rubric().score(case, observation(case, sources=0))
        assert not EvaluationReport(scores=(score,)).passed()

    def test_every_paraphrase_targets_a_canonical_case(self) -> None:
        cases = ScenarioCatalogue().cases()
        canonical = {c.number: c for c in cases if c.variant == "canonical"}
        paraphrases = [c for c in cases if c.variant == "paraphrase"]
        assert {c.number for c in paraphrases} == {5, 6, 8}
        for case in paraphrases:
            twin = canonical[case.number]
            assert case.prompt != twin.prompt or case.completion != twin.completion
            assert case.expected_gate == twin.expected_gate
            assert case.expect_refused == twin.expect_refused

    def test_an_observation_of_another_variant_is_refused(self) -> None:
        cases = ScenarioCatalogue().cases()
        canonical = next(c for c in cases if c.number == 5)
        paraphrase = next(
            c for c in cases if c.number == 5 and c.variant == "paraphrase"
        )
        with pytest.raises(ValueError, match="different case"):
            Rubric().score(canonical, observation(paraphrase))

    def test_the_report_is_synthetic_until_tutor_sourced(self) -> None:
        assert EvaluationReport(scores=()).label == "synthetic-only"


class TestSessionEvents:
    def test_a_paused_turn_does_not_hide_the_turns_after_it(self) -> None:
        paused = SealedRecords().halted(0)
        later = SealedRecords().generated(1, paused.record_hash)
        events = SessionEvents().events(SESSION_ID, (paused, later), ())
        turns = [event.turn_id for event in events]
        assert later.turn_id in turns
        assert events[-1].kind == "draft"

    def test_each_gate_state_has_its_own_kind(self) -> None:
        record = SealedRecords().generated()
        gates = (
            GateEvaluation(
                gate_name=name,
                decision=decision,
                reason="r",
                policy_rule_id="p",
                evaluated_at=record.recorded_at,
            )
            for name, decision in zip(
                GATE_ORDER,
                ("pass", "pause", "not_evaluated", "not_evaluated"),
                strict=True,
            )
        )
        record = record.model_copy(update={"gate_evaluations": tuple(gates)})
        kinds = [
            event.kind
            for event in SessionEvents().events(SESSION_ID, (record,), ())
            if event.gate_name is not None
        ]
        assert kinds == ["gate", "halt", "skipped", "skipped"]

    def test_a_late_action_on_an_early_turn_comes_after_later_turns(self) -> None:
        first = SealedRecords().generated(0)
        second = SealedRecords().generated(1, first.record_hash)
        late = (
            Samples()
            .human_action()
            .model_copy(
                update={
                    "turn_id": first.turn_id,
                    "acted_at": second.recorded_at + timedelta(minutes=5),
                }
            )
        )
        events = SessionEvents().events(SESSION_ID, (first, second), (late,))
        assert events[-1].kind == "action"
        assert events[-1].turn_id == first.turn_id

    def test_a_cursor_resumes_after_the_frame_already_seen(self) -> None:
        record = SealedRecords().generated()
        stream = SessionEvents()
        events = stream.events(SESSION_ID, (record,), ())
        resumed = stream.after(events, events[1].event_id)
        assert resumed == events[2:]

    def test_an_unknown_cursor_replays_everything(self) -> None:
        record = SealedRecords().generated()
        stream = SessionEvents()
        events = stream.events(SESSION_ID, (record,), ())
        assert stream.after(events, "not-an-id") == events

    def test_the_prompt_frame_carries_the_redacted_text(self) -> None:
        record = SealedRecords().generated()
        first = SessionEvents().events(SESSION_ID, (record,), ())[0]
        assert first.kind == "prompt"
        assert first.text == record.learner_prompt.text


class TestEventFrames:
    def test_frames_carry_id_kind_and_a_retry_hint(self) -> None:
        record = SealedRecords().generated()
        events = SessionEvents().events(SESSION_ID, (record,), ())
        body = SseEncoder().encode(events)
        assert body.startswith(f"retry: {SseEncoder.RETRY_MILLISECONDS}\n\n")
        assert f"id: {record.turn_id}:prompt\nevent: prompt\n" in body
        assert body.count("data: ") == len(events)


class TestEvidencePack:
    def test_two_packs_differ_only_by_the_generation_timestamp(self) -> None:
        sources = EvidenceSources(
            commit="abc",
            lockfile_sha256="a" * 64,
            model_revision="b" * 64,
            runtime="3.12.0",
            policy_version="prototype-1",
            chain_status="intact",
            field_label="synthetic-only",
        )
        early = FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))
        later = FrozenClock(datetime(2026, 1, 2, tzinfo=UTC))
        first = EvidencePack(early).files(sources)
        second = EvidencePack(later).files(sources)
        assert first.keys() == second.keys()
        for name in first:
            if name == "manifest.json":
                stamped = first[name].replace("2026-01-01", "STAMP")
                assert stamped == second[name].replace("2026-01-02", "STAMP")
            else:
                assert first[name] == second[name]
        assert "synthetic-only" in first["article-15.md"]
        assert "Chain verification: intact" in first["article-12.md"]
        assert "REQ-AUDIT" in first["article-12.md"]

    def test_the_manifest_is_json_even_when_a_value_has_a_quote(self) -> None:
        sources = EvidenceSources(
            commit='abc"def',
            lockfile_sha256="a" * 64,
            model_revision="b" * 64,
            runtime="3.12.0",
            policy_version="prototype-1",
            chain_status="broken",
            field_label="synthetic-only",
            sessions=2,
            broken_sessions=("s-1",),
        )
        files = EvidencePack(FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))).files(
            sources
        )
        manifest = json.loads(files["manifest.json"])
        assert manifest["commit"] == 'abc"def'
        assert manifest["broken_sessions"] == ["s-1"]
        assert "Broken sessions: s-1" in files["article-12.md"]
