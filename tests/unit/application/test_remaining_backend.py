"""Registry order, replay, rubric, and event frames."""

from datetime import UTC, datetime

import pytest
from tests.support.samples import Samples
from tests.support.scripted_model import ScriptedLanguageModel

from tutor_api.adapters.frozen_clock import FrozenClock
from tutor_api.evidence.pack import EvidencePack, EvidenceSources
from tutor_core.application.evaluation.rubric import (
    Rubric,
    ScenarioResult,
    SyntheticBaseline,
)
from tutor_core.application.services.session_surface import SseEncoder
from tutor_core.application.turn.replay import ReplayRejected, TurnReplay
from tutor_core.domain.audit.record_hash import AuditRecordHash
from tutor_core.domain.gates.registry import GateRegistry
from tutor_core.domain.models.audit import GATE_ORDER
from tutor_core.domain.models.safety import DecodingParams
from tutor_core.domain.models.stream import TurnStreamEvent
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

    def test_a_gate_out_of_order_is_refused(self) -> None:
        swapped = (
            NamedGate(GATE_ORDER[1]),
            NamedGate(GATE_ORDER[0]),
            NamedGate(GATE_ORDER[2]),
            NamedGate(GATE_ORDER[3]),
        )
        with pytest.raises(ValueError, match="permission, conflict"):
            GateRegistry(swapped)


class TestReplay:
    def test_a_matching_clock_and_revision_reproduce_the_output(self) -> None:
        hasher = AuditRecordHash()
        unsealed = (
            Samples().audit_record().model_copy(update={"record_hash": "unsealed"})
        )
        record = unsealed.model_copy(update={"record_hash": hasher.digest(unsealed)})
        clock = FrozenClock(record.recorded_at)
        model = ScriptedLanguageModel(
            "unused",
            record.model_revision or "missing",
            DecodingParams(temperature=0.0, top_p=1.0, max_tokens=16),
        )
        replay = TurnReplay(model, clock, hasher)
        output = replay.output(record)
        assert output.turn_output == record.output_after_checks
        assert replay.resolve(output.checkpoint_id, (record,)) is record

    def test_a_revision_mismatch_fails_closed(self) -> None:
        record = Samples().audit_record()
        model = ScriptedLanguageModel(
            "unused",
            "b" * 64,
            DecodingParams(temperature=0.0, top_p=1.0, max_tokens=16),
        )
        replay = TurnReplay(model, FrozenClock(record.recorded_at), AuditRecordHash())
        with pytest.raises(ReplayRejected, match="revision"):
            replay.output(record)

    def test_a_clock_mismatch_fails_closed(self) -> None:
        record = Samples().audit_record()
        model = ScriptedLanguageModel(
            "unused",
            record.model_revision or "missing",
            DecodingParams(temperature=0.0, top_p=1.0, max_tokens=16),
        )
        replay = TurnReplay(
            model,
            FrozenClock(datetime(1999, 1, 1, tzinfo=UTC)),
            AuditRecordHash(),
        )
        with pytest.raises(ReplayRejected, match="clock"):
            replay.output(record)


class TestRubric:
    def test_two_runs_match_and_the_judge_is_secondary(self) -> None:
        baseline = SyntheticBaseline().rows()
        again = SyntheticBaseline().rows()
        assert baseline == again
        assert {row.judge_signal for row in baseline} == {"secondary"}
        assert [row.correctness for row in baseline] == [1] * 8

    def test_a_missed_gate_scores_zero(self) -> None:
        score = Rubric().score(
            ScenarioResult(
                case_number=4,
                name="ambiguous",
                gate="context_and_permission",
                model_calls=0,
                refused=False,
                status="held_for_review",
            ),
            "conflict_and_ambiguity",
        )
        assert score.correctness == 0


class TestEventFrames:
    def test_a_reconnect_omits_the_frame_already_seen(self) -> None:
        event = TurnStreamEvent(
            event_id="turn:gate",
            kind="gate",
            turn_id=Samples().audit_record().turn_id,
            session_id=Samples().audit_record().session_id,
            gate_name="context_and_permission",
            decision="pass",
        )
        body = SseEncoder().encode((event,))
        assert body.startswith("id: turn:gate\nevent: gate\n")
        assert "data: " in body


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
