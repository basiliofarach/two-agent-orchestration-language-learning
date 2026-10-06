"""The session norm the drift gate compares a turn with (REQ-GATES)."""

import pytest
from pydantic import ValidationError
from tests.support.dashboard_stubs import SealedRecords
from tests.support.samples import Samples

from tutor_core.application.turn.baseline import SessionBaselineCalculator
from tutor_core.domain.models.session_baseline import SessionBaseline


class TestSessionBaselineCalculator:
    def test_a_new_session_has_no_norm(self) -> None:
        baseline = SessionBaselineCalculator().baseline(())
        assert baseline == SessionBaseline()
        assert baseline.mean_support_ratio is None

    def test_the_norm_is_taken_from_drafts_the_model_wrote(self) -> None:
        generated = SealedRecords().generated(0)
        halted = SealedRecords().halted(1, generated.record_hash)
        baseline = SessionBaselineCalculator().baseline((generated, halted))
        assert baseline.prior_turns == 2
        assert baseline.generated_turns == 1
        assert baseline.mean_support_ratio == Samples().support().support_ratio
        assert baseline.mean_output_characters == len("Hola means hello.")

    def test_prompts_with_a_high_severity_flag_are_counted(self) -> None:
        high = Samples().safety_flag().model_copy(update={"severity": "high"})
        low = Samples().safety_flag().model_copy(update={"severity": "low"})
        records = (
            SealedRecords()
            .halted(0)
            .model_copy(update={"prompt_safety_flags": (high,)}),
            SealedRecords()
            .halted(1)
            .model_copy(update={"prompt_safety_flags": (low,)}),
            SealedRecords().halted(2),
        )
        assert SessionBaselineCalculator().baseline(records).flagged_prompts == 1


class TestSessionBaseline:
    def test_counts_cannot_be_negative(self) -> None:
        with pytest.raises(ValidationError):
            SessionBaseline(prior_turns=-1)

    def test_it_is_frozen(self) -> None:
        with pytest.raises(ValidationError):
            SessionBaseline().prior_turns = 3  # type: ignore[misc]

    def test_an_undeclared_field_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SessionBaseline.model_validate({"learner_name": "Ada"})
