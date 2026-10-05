"""ConductTurn's handlers and the record each turn seals."""

import pytest
from pydantic import ValidationError
from tests.support.gate_card import CardPolicy, GateCard
from tests.support.samples import Samples
from tests.support.scripted_connection import ScriptedConnection
from tests.support.turn_stubs import FlaggingSafety, ScriptedGate

from tutor_api.adapters.checks.pii_redaction import RegexPiiRedactor, StandardPiiSteps
from tutor_api.adapters.frozen_clock import FrozenClock
from tutor_core.application.services.conduct_turn import (
    ExecuteTurn,
    FinaliseTurn,
    PrepareTurn,
    TurnFailed,
)
from tutor_core.application.turn.orchestrator import TurnOrchestrator
from tutor_core.application.turn.record import GateRows, TurnRecordBuilder
from tutor_core.application.turn.state import TurnGraphState
from tutor_core.domain.audit.record_hash import AuditRecordHash
from tutor_core.domain.models.audit import ChainHead, TurnAuditRecord
from tutor_core.domain.models.conduct import ExecutedTurn, PreparedTurn, TurnCommand
from tutor_core.domain.models.pipeline import GeneratedDraft
from tutor_core.domain.models.turn import TurnState
from tutor_core.domain.models.verdict import GateDecision, GateVerdict
from tutor_core.domain.ports.audit_sink import AuditSinkPort
from tutor_core.domain.ports.unit_of_work import TransactionalWork, UnitOfWorkPort

_GENESIS = AuditRecordHash.GENESIS


class Verdicts:
    def of(self, *decisions: GateDecision) -> tuple[GateVerdict, ...]:
        names = (
            "context_and_permission",
            "conflict_and_ambiguity",
            "sensitivity_and_high_stakes",
            "drift_and_anomaly",
        )
        return tuple(
            GateVerdict(
                gate_name=name,
                decision=decision,
                reason=f"{name} {decision}",
                policy_rule_id=f"rule-{name}",
            )
            for name, decision in zip(names, decisions, strict=False)
        )


class States:
    def draft(self) -> GeneratedDraft:
        return GeneratedDraft(
            unit=Samples().generated(),
            safety_flags=(Samples().safety_flag(),),
            template_version="tpl-1",
            model_revision="a" * 64,
            decoding_params=Samples().decoding(),
        )

    def passed(self) -> TurnGraphState:
        return TurnGraphState(
            turn=Samples().turn(),
            verdicts=Verdicts().of("pass", "pass", "pass", "pass"),
            draft=self.draft(),
        )

    def stopped_at_permission(self) -> TurnGraphState:
        turn = Samples().turn()
        turn.retrieved = None
        turn.generated = None
        return TurnGraphState(turn=turn, verdicts=Verdicts().of("stop"))


class Builder:
    def build(self) -> TurnRecordBuilder:
        return TurnRecordBuilder(AuditRecordHash(), GateRows())

    def record(self, state: TurnGraphState) -> TurnAuditRecord:
        return self.build().build(
            state,
            ChainHead(previous_record_hash=_GENESIS, turn_index=0),
            "policy-gates",
            Samples().when(),
        )


class TestGateRows:
    def test_unreached_gates_are_not_evaluated_and_cite_the_halting_rule(
        self,
    ) -> None:
        rows = GateRows().rows(Verdicts().of("pass", "pause"), Samples().when())
        assert [row.decision for row in rows] == [
            "pass",
            "pause",
            "not_evaluated",
            "not_evaluated",
        ]
        assert rows[2].policy_rule_id == "rule-conflict_and_ambiguity"
        assert "conflict_and_ambiguity returned pause" in rows[3].reason

    def test_no_verdict_or_too_many_is_refused(self) -> None:
        with pytest.raises(ValueError, match="between one and four"):
            GateRows().rows((), Samples().when())
        five = (*Verdicts().of("pass", "pass", "pass", "pass"), Samples().verdict())
        with pytest.raises(ValueError, match="between one and four"):
            GateRows().rows(five, Samples().when())


class TestTurnRecordBuilder:
    def test_a_passed_turn_records_generation_and_four_passes(self) -> None:
        record = Builder().record(States().passed())
        assert record.model_revision == "a" * 64
        assert record.output_before_checks == Samples().generated().output_before_checks
        assert [row.decision for row in record.gate_evaluations] == ["pass"] * 4
        assert record.retrieved_context_ids == (str(Samples().snippet().chunk_id),)
        assert record.record_hash == AuditRecordHash().digest(record)

    def test_a_permission_stop_records_one_stop_three_unreached_and_no_model(
        self,
    ) -> None:
        record = Builder().record(States().stopped_at_permission())
        assert [row.decision for row in record.gate_evaluations] == [
            "stop",
            "not_evaluated",
            "not_evaluated",
            "not_evaluated",
        ]
        assert record.model_revision is None
        assert record.output_before_checks is None
        assert record.retrieved_context_ids == ()

    def test_a_refusal_before_the_model_records_no_generation(self) -> None:
        state = States().passed()
        state.draft = GeneratedDraft(
            unit=Samples()
            .generated()
            .model_copy(
                update={
                    "output_before_checks": None,
                    "refused": True,
                    "refusal_reason": "open web",
                }
            ),
            safety_flags=(),
        )
        record = Builder().record(state)
        assert record.model_revision is None
        assert record.ai_disclosure is None

    def test_the_record_is_a_snapshot_not_the_live_turn(self) -> None:
        state = States().passed()
        record = Builder().record(state)
        state.turn.learner_prompt = (
            Samples().redacted().model_copy(update={"text": "changed later"})
        )
        assert record.learner_prompt.text == Samples().redacted().text

    def test_a_turn_without_a_redacted_prompt_is_not_recorded(self) -> None:
        state = States().passed()
        state.turn.learner_prompt = None
        with pytest.raises(ValueError, match="redacted"):
            Builder().record(state)

    def test_gate_rows_out_of_order_are_rejected_by_the_record(self) -> None:
        record = Builder().record(States().passed())
        with pytest.raises(ValidationError, match="REQ-GATES order"):
            TurnAuditRecord.model_validate(
                {
                    **record.model_dump(),
                    "gate_evaluations": tuple(reversed(record.gate_evaluations)),
                }
            )

    def test_a_gate_row_is_covered_by_the_digest(self) -> None:
        record = Builder().record(States().passed())
        edited = record.model_copy(
            update={
                "gate_evaluations": (
                    record.gate_evaluations[0].model_copy(update={"reason": "edited"}),
                    *record.gate_evaluations[1:],
                )
            }
        )
        assert AuditRecordHash().digest(edited) != record.record_hash


class TestPrepareTurn:
    def _prepare(self) -> PrepareTurn:
        high = (
            Samples()
            .safety_flag()
            .model_copy(update={"category": "out_of_scope", "severity": "high"})
        )
        return PrepareTurn(
            RegexPiiRedactor(StandardPiiSteps().steps()),
            FlaggingSafety((high,)),
            ("out_of_scope",),
        )

    def _command(self, prompt: str) -> TurnCommand:
        return TurnCommand(
            session_id=Samples().turn().session_id,
            learner_id=Samples().learner_id().value,
            prompt=prompt,
            requested_history_fields=("proficiency_level",),
        )

    def test_the_prompt_is_redacted_before_anything_else_sees_it(self) -> None:
        prepared = self._prepare().run(self._command("My name is Ada. What is hola?"))
        prompt = prepared.turn.learner_prompt
        assert prompt is not None
        assert "Ada" not in prompt.text
        assert prompt.redaction_count >= 1
        assert prepared.turn.requested_history_fields == ("proficiency_level",)
        assert prepared.turn.requires_unvetted_source is False

    def test_an_open_web_question_is_marked_as_needing_an_unvetted_source(
        self,
    ) -> None:
        prepared = self._prepare().run(self._command("Search the web for hola"))
        assert prepared.turn.requires_unvetted_source is True

    def test_each_turn_gets_its_own_identifier(self) -> None:
        first = self._prepare().run(self._command("hola"))
        second = self._prepare().run(self._command("hola"))
        assert first.turn.turn_id != second.turn.turn_id


class FixedOrchestrator(TurnOrchestrator):
    def __init__(self, state: TurnGraphState) -> None:
        self._state = state

    async def run(self, turn: TurnState) -> TurnGraphState:
        return self._state


class MemorySink(AuditSinkPort):
    def __init__(self) -> None:
        self.records: list[TurnAuditRecord] = []

    async def head(self, session_id: object) -> ChainHead:  # type: ignore[override]
        return ChainHead(previous_record_hash=_GENESIS, turn_index=len(self.records))

    async def append(self, record: TurnAuditRecord) -> None:
        self.records.append(record)


class ScriptedUnit(UnitOfWorkPort):
    """Runs the work on a scripted connection, or skips it, or fails."""

    def __init__(self, mode: str = "run") -> None:
        self._mode = mode

    async def run(self, work: TransactionalWork) -> None:
        if self._mode == "fail":
            msg = "connection lost"
            raise ConnectionError(msg)
        if self._mode == "run":
            await work.run(ScriptedConnection())


class Execute:
    def handler(
        self, unit: UnitOfWorkPort, sink: AuditSinkPort | None = None
    ) -> ExecuteTurn:
        return ExecuteTurn(
            unit,
            FixedOrchestrator(States().passed()),
            sink if sink is not None else MemorySink(),
            CardPolicy(GateCard().build()),
            Builder().build(),
            FrozenClock(Samples().when()),
        )

    def prepared(self) -> PreparedTurn:
        return PreparedTurn(turn=Samples().turn())


class TestExecuteTurn:
    async def test_the_record_is_appended_and_returned(self) -> None:
        sink = MemorySink()
        executed = (
            await Execute().handler(ScriptedUnit(), sink).run(Execute().prepared())
        )
        assert sink.records == [executed.record]
        assert executed.record.policy_version == "policy-gates"
        assert executed.record.recorded_at == Samples().when()
        assert executed.draft == States().draft()

    async def test_a_failure_in_the_unit_of_work_is_a_turn_failure(self) -> None:
        with pytest.raises(TurnFailed, match="ConnectionError"):
            await Execute().handler(ScriptedUnit("fail")).run(Execute().prepared())

    async def test_a_unit_of_work_that_skipped_the_turn_is_a_turn_failure(
        self,
    ) -> None:
        with pytest.raises(TurnFailed, match="without running the turn"):
            await Execute().handler(ScriptedUnit("skip")).run(Execute().prepared())


class TestFinaliseTurn:
    def test_a_turn_that_passed_awaits_the_tutor(self) -> None:
        state = States().passed()
        outcome = FinaliseTurn().run(
            ExecutedTurn(
                record=Builder().record(state),
                draft=state.draft,
                retrieved=state.turn.retrieved,
            )
        )
        assert outcome.status == "awaiting_tutor_approval"
        assert outcome.halted_at is None
        assert outcome.reply == Samples().generated().output_after_checks
        assert outcome.ai_disclosure
        assert outcome.unsupported_claims == ("invented claim",)
        assert outcome.sources == (Samples().source().source_uri,)

    def test_a_halted_turn_is_held_and_names_the_gate(self) -> None:
        state = States().stopped_at_permission()
        outcome = FinaliseTurn().run(
            ExecutedTurn(record=Builder().record(state), draft=None, retrieved=None)
        )
        assert outcome.status == "held_for_review"
        assert outcome.halted_at == "context_and_permission"
        assert outcome.reply is None
        assert outcome.refused is False
        assert outcome.sources == ()
        assert len(outcome.gates) == 4

    def test_scripted_gate_names_itself(self) -> None:
        assert ScriptedGate("pass", "drift_and_anomaly").name() == "drift_and_anomaly"
