"""Validation, immutability, and the REQ-AUDIT / DEC-0010 model contracts."""

import ast
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import get_args

import pytest
from pydantic import BaseModel, ValidationError
from tests.support.frozen import FrozenModelChecks, ModelId
from tests.support.samples import Samples
from tests.support.timezones import OffsetlessTimezone

from tutor_core.domain import models as model_package
from tutor_core.domain import policy as policy_package
from tutor_core.domain.models.audit import HumanAction, TurnAuditRecord
from tutor_core.domain.models.retrieval import RetrievalResult
from tutor_core.domain.models.safety import (
    ClaimSpan,
    GeneratedUnit,
    RedactedText,
    SourceSupportReport,
)
from tutor_core.domain.models.turn import TurnState
from tutor_core.domain.models.verdict import GateDecision, GateStage, GateVerdict
from tutor_core.domain.policy.policy_card import PolicyCard

_FROZEN = Samples().frozen_instances()


class TestEveryModelRejectsABadPayload:
    @pytest.mark.parametrize(
        "model",
        _FROZEN,
        ids=ModelId(),
    )
    def test_validation_rejects_bad_input(self, model: BaseModel) -> None:
        with pytest.raises(ValidationError):
            type(model).model_validate({"undeclared": True})


class TestFrozenAuditAndEvidenceModels:
    @pytest.mark.parametrize("model", _FROZEN, ids=ModelId())
    def test_assignment_raises_validation_error(self, model: BaseModel) -> None:
        FrozenModelChecks().assert_assignment_raises(model)

    @pytest.mark.parametrize("model", _FROZEN, ids=ModelId())
    def test_undeclared_field_is_rejected(self, model: BaseModel) -> None:
        FrozenModelChecks().assert_extra_forbidden(model)

    @pytest.mark.parametrize("model", _FROZEN, ids=ModelId())
    def test_models_are_hashable_and_equal_by_value(self, model: BaseModel) -> None:
        FrozenModelChecks().assert_equal_and_hashable(model)

    @pytest.mark.parametrize("model", _FROZEN, ids=ModelId())
    def test_list_passed_to_a_tuple_field_is_coerced(self, model: BaseModel) -> None:
        FrozenModelChecks().assert_list_coerced_to_tuple(model)


class TestGateVerdict:
    def test_decision_is_pass_pause_or_stop(self) -> None:
        for decision in ("pass", "pause", "stop"):
            verdict = GateVerdict(
                gate_name="conflict_and_ambiguity",
                decision=decision,
                reason="recorded",
                policy_rule_id="rule-1",
            )
            assert verdict.decision == decision
        assert set(get_args(GateDecision)) == {"pass", "pause", "stop"}

    def test_unknown_decision_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GateVerdict.model_validate(
                {
                    "gate_name": "conflict_and_ambiguity",
                    "decision": "maybe",
                    "reason": "recorded",
                    "policy_rule_id": "rule-1",
                }
            )

    def test_safety_flags_are_not_a_verdict_field(self) -> None:
        with pytest.raises(ValidationError):
            GateVerdict.model_validate(
                {
                    "gate_name": "sensitivity",
                    "decision": "pause",
                    "reason": "flagged",
                    "policy_rule_id": "rule-1",
                    "safety_flags": [],
                }
            )

    def test_gate_stage_names_the_four_graph_points(self) -> None:
        assert set(get_args(GateStage)) == {
            "context_and_permission",
            "conflict_and_ambiguity",
            "sensitivity_and_high_stakes",
            "drift_and_anomaly",
        }


class TestTurnAuditRecord:
    def test_prompt_is_stored_not_digested(self) -> None:
        prompt = "Where is the library?"
        record = Samples().audit_record()
        assert record.learner_prompt_redacted == prompt
        assert " " in record.learner_prompt_redacted

    def test_output_before_and_after_checks_are_both_kept(self) -> None:
        record = TurnAuditRecord.model_validate(
            {
                **Samples().audit_record().model_dump(),
                "output_before_checks": "before",
                "output_after_checks": "after",
            }
        )
        assert record.output_before_checks == "before"
        assert record.output_after_checks == "after"

    def test_recorded_at_is_required(self) -> None:
        payload = Samples().audit_record().model_dump()
        del payload["recorded_at"]
        with pytest.raises(ValidationError):
            TurnAuditRecord.model_validate(payload)

    def test_naive_recorded_at_is_rejected(self) -> None:
        payload = Samples().audit_record().model_dump()
        payload["recorded_at"] = datetime(2026, 9, 21, 12, 0)
        with pytest.raises(ValidationError):
            TurnAuditRecord.model_validate(payload)

    def test_offsetless_timezone_on_recorded_at_is_rejected(self) -> None:
        payload = Samples().audit_record().model_dump()
        payload["recorded_at"] = datetime(
            2026, 9, 21, 12, 0, tzinfo=OffsetlessTimezone()
        )
        with pytest.raises(ValidationError):
            TurnAuditRecord.model_validate(payload)

    def test_offset_recorded_at_is_normalised_to_utc(self) -> None:
        payload = Samples().audit_record().model_dump()
        payload["recorded_at"] = datetime(
            2026, 9, 21, 12, 0, tzinfo=timezone(timedelta(hours=2))
        )
        record = TurnAuditRecord.model_validate(payload)
        assert record.recorded_at.tzinfo is UTC
        assert record.recorded_at == datetime(2026, 9, 21, 10, 0, tzinfo=UTC)

    def test_same_instant_in_two_offsets_serialises_identically(self) -> None:
        payload = Samples().audit_record().model_dump()
        east = {
            **payload,
            "recorded_at": datetime(
                2026, 9, 21, 12, 0, tzinfo=timezone(timedelta(hours=2))
            ),
        }
        utc = {**payload, "recorded_at": datetime(2026, 9, 21, 10, 0, tzinfo=UTC)}
        assert (
            TurnAuditRecord.model_validate(east).model_dump_json()
            == TurnAuditRecord.model_validate(utc).model_dump_json()
        )


class TestTurnAuditRecordStops:
    def test_a_permission_stop_has_no_generation_fields(self) -> None:
        record = Samples().stopped_audit_record()
        assert record.session_id == Samples().turn().session_id
        assert record.turn_index == 0
        assert record.model_revision is None
        assert record.template_version is None
        assert record.decoding_params is None
        assert record.output_before_checks is None
        assert record.output_after_checks is None
        assert record.ai_disclosure is None
        assert record.refused is None
        assert record.safety_flags is None
        assert record.source_support is None
        assert record.retrieved_context_ids == ()

    def test_absent_generation_fields_stay_in_the_record(self) -> None:
        dumped = Samples().stopped_audit_record().model_dump(mode="json")
        generated = Samples().audit_record().model_dump(mode="json")
        assert dumped["model_revision"] is None
        assert dumped["output_before_checks"] is None
        assert dumped["output_after_checks"] is None
        assert generated["model_revision"] is not None
        assert dumped.keys() == generated.keys()

    def test_a_stop_path_cannot_invent_a_model_revision(self) -> None:
        payload = Samples().stopped_audit_record().model_dump()
        payload["model_revision"] = "a" * 40
        with pytest.raises(ValidationError, match="no model revision and no outputs"):
            TurnAuditRecord.model_validate(payload)


class TestHumanAction:
    def test_edit_requires_edited_output(self) -> None:
        with pytest.raises(ValidationError):
            HumanAction(
                turn_id=Samples().human_action().turn_id,
                tutor_id="tutor-1",
                action="edit",
                edited_output=None,
                acted_at=datetime(2026, 9, 21, 12, 0, tzinfo=UTC),
            )

    def test_blank_edit_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            HumanAction(
                turn_id=Samples().human_action().turn_id,
                tutor_id="tutor-1",
                action="edit",
                edited_output="  ",
                acted_at=datetime(2026, 9, 21, 12, 0, tzinfo=UTC),
            )

    def test_edit_keeps_the_tutor_text(self) -> None:
        action = HumanAction(
            turn_id=Samples().human_action().turn_id,
            tutor_id="tutor-1",
            action="edit",
            edited_output="Hola.",
            acted_at=datetime(2026, 9, 21, 12, 0, tzinfo=UTC),
        )
        assert action.edited_output == "Hola."

    def test_naive_acted_at_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            HumanAction(
                turn_id=Samples().human_action().turn_id,
                tutor_id="tutor-1",
                action="stop",
                acted_at=datetime(2026, 9, 21, 12, 0),
            )

    def test_offsetless_timezone_on_acted_at_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            HumanAction(
                turn_id=Samples().human_action().turn_id,
                tutor_id="tutor-1",
                action="stop",
                acted_at=datetime(2026, 9, 21, 12, 0, tzinfo=OffsetlessTimezone()),
            )

    def test_offset_acted_at_is_normalised_to_utc(self) -> None:
        action = HumanAction(
            turn_id=Samples().human_action().turn_id,
            tutor_id="tutor-1",
            action="stop",
            acted_at=datetime(2026, 9, 21, 12, 0, tzinfo=timezone(timedelta(hours=2))),
        )
        assert action.acted_at == datetime(2026, 9, 21, 10, 0, tzinfo=UTC)
        assert action.acted_at.tzinfo is UTC


class TestTurnState:
    def test_is_not_frozen(self) -> None:
        assert TurnState.model_config.get("frozen", False) is False
        assert TurnState.model_config["extra"] == "forbid"

    def test_assignment_accumulates_the_turn(self) -> None:
        samples = Samples()
        state = TurnState(
            turn_id=samples.turn().turn_id,
            session_id=samples.turn().session_id,
        )
        assert state.learner_prompt is None
        assert state.retrieved is None
        assert state.generated is None
        state.learner_prompt = samples.redacted()
        state.retrieved = samples.retrieval()
        state.generated = samples.generated()
        state.safety_flags = (samples.safety_flag(),)
        assert state.learner_prompt == samples.redacted()
        assert state.retrieved == samples.retrieval()
        assert state.generated == samples.generated()
        assert state.safety_flags == (samples.safety_flag(),)

    def test_undeclared_field_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TurnState.model_validate(
                {
                    "turn_id": Samples().turn().turn_id,
                    "session_id": Samples().turn().session_id,
                    "raw_prompt": "unredacted",
                }
            )

    def test_validation_rejects_bad_input(self) -> None:
        with pytest.raises(ValidationError):
            TurnState.model_validate({"turn_id": "not-a-uuid"})


class TestRedactedText:
    def test_zero_redactions_require_empty_categories(self) -> None:
        with pytest.raises(ValidationError):
            RedactedText(
                text="hello", redacted_categories=("email",), redaction_count=0
            )

    def test_positive_count_requires_categories(self) -> None:
        with pytest.raises(ValidationError):
            RedactedText(text="hello", redacted_categories=(), redaction_count=2)

    def test_categories_are_kept_beside_the_text(self) -> None:
        redacted = RedactedText(
            text="contact [REDACTED]",
            redacted_categories=["email"],
            redaction_count=1,
        )
        assert redacted.text == "contact [REDACTED]"
        assert redacted.redacted_categories == ("email",)


class TestRetrievalResult:
    def test_snippet_source_must_be_listed(self) -> None:
        samples = Samples()
        other = samples.source().model_copy(
            update={"source_uri": "kb://other"},
        )
        with pytest.raises(ValidationError):
            RetrievalResult(
                snippets=(samples.snippet(),),
                sources=(other,),
                confidence=0.5,
            )

    def test_empty_retrieval_is_valid(self) -> None:
        result = RetrievalResult(snippets=(), sources=(), confidence=0.0)
        assert result.snippets == ()

    def test_confidence_above_one_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RetrievalResult(snippets=(), sources=(), confidence=1.5)


class TestSourceSupportReport:
    def test_unsupported_spans_are_kept(self) -> None:
        report = Samples().support()
        assert report.unsupported == (Samples().unsupported_span(),)
        assert report.supported == (Samples().supported_span(),)

    def test_span_end_before_start_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ClaimSpan(text="backwards", start=4, end=1)


class TestGeneratedUnit:
    def test_disclosure_is_required(self) -> None:
        payload = Samples().generated().model_dump()
        payload["ai_disclosure"] = "  "
        with pytest.raises(ValidationError):
            GeneratedUnit.model_validate(payload)

    def test_refusal_requires_a_reason(self) -> None:
        payload = Samples().generated().model_dump()
        payload["refused"] = True
        payload["refusal_reason"] = None
        with pytest.raises(ValidationError):
            GeneratedUnit.model_validate(payload)

    def test_blank_refusal_reason_is_rejected(self) -> None:
        payload = Samples().generated().model_dump()
        payload["refused"] = True
        payload["refusal_reason"] = " "
        with pytest.raises(ValidationError):
            GeneratedUnit.model_validate(payload)

    def test_refusal_reason_is_absent_unless_refused(self) -> None:
        payload = Samples().generated().model_dump()
        payload["refused"] = False
        payload["refusal_reason"] = "not refused"
        with pytest.raises(ValidationError):
            GeneratedUnit.model_validate(payload)

    def test_refused_unit_keeps_disclosure_and_reason(self) -> None:
        payload = Samples().generated().model_dump()
        payload["refused"] = True
        payload["refusal_reason"] = "out of scope"
        unit = GeneratedUnit.model_validate(payload)
        assert unit.refused is True
        assert unit.refusal_reason == "out of scope"
        assert unit.ai_disclosure.strip()


class TestPolicyCard:
    def test_empty_version_is_rejected(self) -> None:
        payload = Samples().policy_card().model_dump()
        payload["version"] = ""
        with pytest.raises(ValidationError):
            PolicyCard.model_validate(payload)


class DatetimeNowCalls:
    """True when source code calls ``now``, ignoring mentions in docstrings."""

    def in_tree(self, root: Path) -> list[str]:
        return [
            path.name
            for path in sorted(root.glob("*.py"))
            if self._calls_now(path.read_text(encoding="utf-8"))
        ]

    def _calls_now(self, source: str) -> bool:
        for node in ast.walk(ast.parse(source)):
            called = isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            if called and node.func.attr == "now":
                return True
        return False


class TestModelsDoNotReadTheClock:
    def test_sources_do_not_call_datetime_now(self) -> None:
        roots = (
            Path(model_package.__file__).resolve().parent,
            Path(policy_package.__file__).resolve().parent,
        )
        scan = DatetimeNowCalls()
        offenders = [name for root in roots for name in scan.in_tree(root)]
        assert offenders == []


class TestSourceSupportRatio:
    def test_ratio_above_one_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SourceSupportReport(supported=(), unsupported=(), support_ratio=2.0)
