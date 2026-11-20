"""A failed API call leaves a trail: the step, the status, and the kind."""

import io
from pathlib import Path

import pytest
from pydantic import ValidationError
from tests.unit.sim.test_kernel import OfflineSettings
from tests.unit.sim.test_simulation_campaign import (
    _LEARNER,
    ScriptedTutor,
    _case,
)

from tutor_sim.application.roles import AbsentTutor, ComplacentTutor
from tutor_sim.application.tier1 import CampaignAbort, FailedCall, Tier1Runner
from tutor_sim.composition import SimulationCompositionRoot
from tutor_sim.domain.models.client_call import LearnerCall, TurnCall
from tutor_sim.domain.models.observation import CampaignLine, CaseFailure
from tutor_sim.settings import SimulationSettings


class TestFailedCall:
    def test_a_failed_call_names_its_status_kind_and_detail(self) -> None:
        call = LearnerCall(http_status=503, kind="errored", detail="ReadTimeout")
        assert FailedCall().describe(call) == "HTTP 503 errored: ReadTimeout"

    def test_a_failed_call_without_detail_names_its_status_and_kind(self) -> None:
        call = TurnCall(http_status=500, kind="unexpected")
        assert FailedCall().describe(call) == "HTTP 500 unexpected"


class TestAbortTrail:
    def test_an_unreadable_roster_aborts_with_the_status_and_detail(self) -> None:
        client = ScriptedTutor()
        client.learners_kind = "errored"
        with pytest.raises(
            CampaignAbort, match="roster could not be read: HTTP 503 errored: down"
        ):
            Tier1Runner(client, AbsentTutor()).run(_case(), "hello", _LEARNER, "t")

    def test_an_unopened_session_aborts_with_the_status_and_detail(self) -> None:
        client = ScriptedTutor()
        client.open_kind = "session_rejected"
        with pytest.raises(
            CampaignAbort, match="did not open: HTTP 422 session_rejected: no"
        ):
            Tier1Runner(client, AbsentTutor()).run(_case(), "hello", _LEARNER, "t")

    def test_an_unhealthy_api_aborts_with_the_status_and_detail(self) -> None:
        client = ScriptedTutor()
        client.health_kind = "errored"
        with pytest.raises(CampaignAbort, match="not healthy: HTTP 503 errored: down"):
            Tier1Runner(client, AbsentTutor()).run(_case(), "hello", _LEARNER, "t")


class TestErroredCaseTrail:
    def _run(self, client: ScriptedTutor, complacent: bool = False) -> CaseFailure:
        role = ComplacentTutor() if complacent else AbsentTutor()
        record = Tier1Runner(client, role).run(_case(), "hello", _LEARNER, "t")
        assert record.errored is True
        assert record.failure is not None
        return record.failure

    def test_a_failed_submit_records_the_step_status_and_kind(self) -> None:
        client = ScriptedTutor()
        client.submit_kind = "errored"
        failure = self._run(client)
        assert failure == CaseFailure(step="submit", http_status=503, kind="errored")

    def test_a_missing_turn_records_the_detail_step(self) -> None:
        client = ScriptedTutor()
        client.detail_kind = "not_found"
        assert self._run(client).step == "detail"

    def test_an_unknown_status_records_the_status_step(self) -> None:
        client = ScriptedTutor()
        client.status = "nope"
        failure = self._run(client)
        assert failure.step == "status"
        assert failure.kind is None

    def test_a_failed_action_records_the_action_step(self) -> None:
        client = ScriptedTutor()
        client.status = "held_for_review"
        client.act_kind = "errored"
        assert self._run(client, complacent=True).step == "action"

    def test_a_failed_replay_and_audit_record_their_steps(self) -> None:
        replay = ScriptedTutor()
        replay.replay_kind = "not_found"
        assert self._run(replay).step == "replay"
        audit = ScriptedTutor()
        audit.audit_kind = "not_found"
        assert self._run(audit).step == "audit"

    def test_a_case_that_ran_has_no_failure(self) -> None:
        record = Tier1Runner(ScriptedTutor(), AbsentTutor()).run(
            _case(), "hello", _LEARNER, "t"
        )
        assert record.failure is None


class TestCaseFailureModel:
    def test_a_failure_carries_no_response_text(self) -> None:
        with pytest.raises(ValidationError):
            CaseFailure.model_validate(
                {"step": "submit", "http_status": 422, "kind": "x", "detail": "t"}
            )

    def test_an_unknown_step_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CaseFailure(step="elsewhere", http_status=503, kind="errored")  # type: ignore[arg-type]

    def test_a_failure_is_frozen(self) -> None:
        failure = CaseFailure(step="submit", http_status=503, kind="errored")
        with pytest.raises(ValidationError):
            failure.step = "detail"  # type: ignore[misc]

    def test_a_campaign_line_written_before_the_field_still_reads(self) -> None:
        line = CampaignLine.model_validate_json('{"case_id": "c1", "errored": true}')
        assert line.failure is None


class TestClientTimeout:
    def test_the_default_waits_long_enough_for_a_local_model_turn(self) -> None:
        assert SimulationSettings().api_timeout_seconds == 600.0

    def test_a_timeout_that_is_not_positive_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            SimulationSettings(api_timeout_seconds=0)

    def test_the_online_client_uses_the_configured_timeout(
        self, tmp_path: Path
    ) -> None:
        settings = OfflineSettings().build(tmp_path, offline=False)
        tuned = settings.model_copy(update={"api_timeout_seconds": 42.0})
        wired = SimulationCompositionRoot(tuned).wire(io.StringIO())
        try:
            assert wired.client is not None
            assert wired.client.timeout.read == 42.0
            assert wired.client.timeout.connect == 42.0
        finally:
            wired.close()


class TestRunCommandTrail:
    def test_an_errored_case_is_named_on_stderr_and_in_the_campaign(
        self, tmp_path: Path
    ) -> None:
        from datetime import UTC, datetime

        from tests.unit.sim.test_kernel import PinnedSource
        from tests.unit.sim.test_simulation_campaign import TestCommands

        from tutor_sim.adapters.file_dataset_store import FileDatasetStore
        from tutor_sim.adapters.frozen_clock import FrozenClock
        from tutor_sim.adapters.role_model import EchoRoleModel
        from tutor_sim.application.commands import CampaignCommands
        from tutor_sim.application.roles import TutorRoster

        settings = OfflineSettings().build(tmp_path, True)
        TestCommands()._plan(settings.dataset_dir)
        client = ScriptedTutor()
        client.submit_kind = "errored"
        errors = io.StringIO()
        commands = CampaignCommands(
            settings,
            FrozenClock(datetime(2026, 1, 1, tzinfo=UTC)),
            FileDatasetStore(settings.dataset_dir),
            EchoRoleModel(),
            (PinnedSource().record(),),
            client,
            AbsentTutor(),
            TutorRoster(()),
            errors,
        )
        assert commands.dispatch("pupil-messages") == 0
        assert commands.dispatch("freeze") == 0
        assert commands.dispatch("run") == 0
        assert "c1 errored at submit: HTTP 503 errored" in errors.getvalue()
        line = CampaignLine.model_validate_json(
            (
                settings.evidence_dir
                / "runs"
                / "run-20260101T000000"
                / "campaign.jsonl"
            ).read_text(encoding="utf-8")
        )
        assert line.failure == CaseFailure(
            step="submit", http_status=503, kind="errored"
        )


class TestCommandNames:
    def test_the_old_realise_name_is_not_a_command(self, tmp_path: Path) -> None:
        from tutor_sim.cli import SimulationCli

        errors = io.StringIO()
        root = SimulationCompositionRoot(OfflineSettings().build(tmp_path, True))
        assert SimulationCli(root, errors).main(["realise"]) == 2
