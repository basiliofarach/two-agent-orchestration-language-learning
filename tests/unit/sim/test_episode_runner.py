"""Tier 2: the pupil reads a release, a stop ends the episode, eight is the cap."""

from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from tutor_sim.adapters.role_model import EchoRoleModel, ScriptedRoleModel
from tutor_sim.application.episode import (
    EpisodePlanFile,
    EpisodeRecord,
    EpisodeRunner,
    TranscriptFile,
)
from tutor_sim.application.oracle import InvariantSet
from tutor_sim.application.roles import (
    AbsentTutor,
    ComplacentTutor,
    DiligentTutor,
    StoppingTutor,
    TutorRoster,
    UnknownTutorRole,
)
from tutor_sim.application.tier1 import CampaignAbort, ModeGuard
from tutor_sim.domain.models.api_views import (
    AuditView,
    GateRowView,
    HealthView,
    HumanActionView,
    LearnerView,
    RecordedActionView,
    ReplayView,
    SessionView,
    TurnDetailView,
    TurnOutcomeView,
)
from tutor_sim.domain.models.case import EpisodeSpec
from tutor_sim.domain.models.client_call import (
    ActionCall,
    AuditCall,
    DetailCall,
    HealthCall,
    LearnerCall,
    ReplayCall,
    SessionCall,
    TurnCall,
)
from tutor_sim.domain.models.episode import EpisodeTurn
from tutor_sim.domain.models.tutor_role import DashboardView, TutorDecision
from tutor_sim.domain.ports.role_model import RoleModelPort
from tutor_sim.domain.ports.tutor_client import TutorClientPort
from tutor_sim.domain.ports.tutor_role import TutorRolePort

_LEARNER = UUID(int=2)
_SESSION = UUID(int=3)
_GATES = (
    "context_and_permission",
    "conflict_and_ambiguity",
    "sensitivity_and_high_stakes",
    "drift_and_anomaly",
)


class RecordingTutor(TutorClientPort):
    """An API that behaves: a recorded stop refuses every later turn with 422.

    The reply is ``release-<index>``. Every call is counted.
    """

    def __init__(self, halt_on: int | None = None) -> None:
        self.prompts: list[str] = []
        self.actions: list[str] = []
        self.reads: list[UUID] = []
        self.replays: list[UUID] = []
        self.audits = 0
        self.opens = 0
        self.stopped = False
        self.probed = False
        self.refuse_after_stop = True
        self.status_override: str | None = None
        self.sources: tuple[str, ...] = ()
        self.retained = (_LEARNER,)
        self._halt_on = halt_on

    def health(self) -> HealthCall:
        return HealthCall(
            http_status=200,
            kind="ok",
            body=HealthView(status="ok", database_configured=True, mode="simulation"),
        )

    def learners(self) -> LearnerCall:
        return LearnerCall(
            http_status=200,
            kind="ok",
            body=tuple(
                LearnerView(learner_id=learner, retained=True)
                for learner in self.retained
            ),
        )

    def open_session(self, learner_id: UUID, tutor_id: str) -> SessionCall:
        self.opens += 1
        self.stopped = False
        self.probed = False
        return SessionCall(
            http_status=200,
            kind="ok",
            body=SessionView(session_id=_SESSION, learner_id=learner_id, open=True),
        )

    def submit(
        self,
        session_id: UUID,
        learner_id: UUID,
        prompt: str,
        fields: tuple[str, ...],
    ) -> TurnCall:
        index = len(self.prompts)
        self.prompts.append(prompt)
        if self.stopped:
            self.probed = True
        if self.stopped and self.refuse_after_stop:
            return TurnCall(
                http_status=422, kind="session_rejected", detail="session stopped"
            )
        halted = "drift_and_anomaly" if index == self._halt_on else None
        status = "held_for_review" if halted else "awaiting_tutor_approval"
        return TurnCall(
            http_status=200,
            kind="ok",
            body=TurnOutcomeView(
                turn_id=UUID(int=10 + index),
                session_id=session_id,
                status=self.status_override or status,
                halted_at=halted,
                refused=False,
                sources=self.sources,
                policy_version="sim-1",
                reply=f"release-{index}",
                gates=tuple(
                    GateRowView(
                        gate_name=name,
                        decision="pause" if name == halted else "pass",
                        policy_rule_id="rule",
                    )
                    for name in _GATES
                ),
            ),
        )

    def detail(self, turn_id: UUID) -> DetailCall:
        self.reads.append(turn_id)
        return DetailCall(
            http_status=200,
            kind="ok",
            body=TurnDetailView(record_intact=True),
        )

    def act(
        self,
        session_id: UUID,
        turn_id: UUID,
        tutor_id: str,
        action: str,
        edited_output: str | None,
    ) -> ActionCall:
        self.actions.append(action)
        if action == "stop":
            self.stopped = True
        return ActionCall(
            http_status=200,
            kind="ok",
            body=RecordedActionView(
                action=HumanActionView(action=action), stopped=self.stopped
            ),
        )

    def audit(self, session_id: UUID) -> AuditCall:
        self.audits += 1
        return AuditCall(http_status=200, kind="ok", body=AuditView(intact=True))

    def replay(self, turn_id: UUID) -> ReplayCall:
        self.replays.append(turn_id)
        return ReplayCall(
            http_status=200,
            kind="ok",
            body=ReplayView(turn_id=turn_id, outcome="reproduced"),
        )


class UnreadableAfterStop(RecordingTutor):
    """Turns read while the episode runs, and stop reading after the probe."""

    def detail(self, turn_id: UUID) -> DetailCall:
        if self.probed:
            return DetailCall(http_status=503, kind="errored")
        return super().detail(turn_id)


class FailingTutor(RecordingTutor):
    """Fails one call with a 503 while the episode runs."""

    def __init__(self, failing: str) -> None:
        super().__init__()
        self._failing = failing

    def learners(self) -> LearnerCall:
        if self._failing == "learners":
            return LearnerCall(http_status=503, kind="errored")
        return super().learners()

    def open_session(self, learner_id: UUID, tutor_id: str) -> SessionCall:
        if self._failing == "open":
            return SessionCall(http_status=503, kind="errored")
        return super().open_session(learner_id, tutor_id)

    def submit(
        self,
        session_id: UUID,
        learner_id: UUID,
        prompt: str,
        fields: tuple[str, ...],
    ) -> TurnCall:
        if self._failing == "submit":
            return TurnCall(http_status=503, kind="errored")
        return super().submit(session_id, learner_id, prompt, fields)

    def act(
        self,
        session_id: UUID,
        turn_id: UUID,
        tutor_id: str,
        action: str,
        edited_output: str | None,
    ) -> ActionCall:
        if self._failing == "act":
            return ActionCall(http_status=503, kind="errored")
        return super().act(session_id, turn_id, tutor_id, action, edited_output)

    def detail(self, turn_id: UUID) -> DetailCall:
        if self._failing == "detail":
            return DetailCall(http_status=503, kind="errored")
        return super().detail(turn_id)

    def replay(self, turn_id: UUID) -> ReplayCall:
        if self._failing == "replay":
            return ReplayCall(http_status=503, kind="errored")
        return super().replay(turn_id)

    def audit(self, session_id: UUID) -> AuditCall:
        if self._failing == "audit":
            return AuditCall(http_status=503, kind="errored")
        return super().audit(session_id)


class ScriptedDecisions(TutorRolePort):
    """Returns the given decisions in order, one per turn."""

    def __init__(self, *decisions: TutorDecision) -> None:
        self._decisions = list(decisions)

    def role(self) -> str:
        return "T2"

    def decide(self, view: DashboardView) -> TutorDecision:
        return self._decisions.pop(0)


class RefusingMode(ModeGuard):
    """A guard that refuses every health result, to show it is the one used."""

    def check(self, health: HealthCall) -> None:
        msg = "refused by the injected guard"
        raise CampaignAbort(msg)


def _spec(role: str, script: str, turns: int, stop: int | None) -> EpisodeSpec:
    return EpisodeSpec(
        episode_id="episode-1",
        persona_id="persona-1",
        tutor_role=role,  # type: ignore[arg-type]
        max_turns=turns,
        script=script,  # type: ignore[arg-type]
        planned_intents=("I1",),
        stop_at_turn=stop,
    )


def _run(
    tmp_path: Path,
    client: TutorClientPort,
    role: TutorRolePort,
    spec: EpisodeSpec,
    pupil: RoleModelPort | None = None,
    mode: ModeGuard | None = None,
) -> EpisodeRecord:
    return EpisodeRunner(
        client,
        role,
        EchoRoleModel() if pupil is None else pupil,
        ModeGuard() if mode is None else mode,
        TranscriptFile(tmp_path),
    ).run(spec, _LEARNER, "tutor", "You are a learner.")


def _inv7(record: EpisodeRecord) -> list[bool]:
    return [InvariantSet().one("INV-7", facts).passed for facts in record.facts]


class TestEpisodeRunner:
    def test_eight_turns_is_the_model_cap(self) -> None:
        with pytest.raises(ValidationError):
            _spec("T2", "open", 9, None)

    def test_an_open_episode_submits_every_turn_and_the_pupil_reads_the_release(
        self, tmp_path: Path
    ) -> None:
        client = RecordingTutor()
        record = _run(tmp_path, client, ComplacentTutor(), _spec("T2", "open", 3, None))
        transcript = record.transcript
        assert len(transcript.turns) == 3
        assert transcript.stopped is False
        assert "release-0" in client.prompts[1]
        assert transcript.turns[0].released == "release-0"

    def test_every_turn_is_read_replayed_and_audited_into_an_observation(
        self, tmp_path: Path
    ) -> None:
        client = RecordingTutor()
        record = _run(tmp_path, client, ComplacentTutor(), _spec("T2", "open", 2, None))
        turn_ids = [turn.turn_id for turn in record.transcript.turns]
        assert client.reads == turn_ids
        assert client.replays == turn_ids
        assert client.audits == 2
        assert [facts.observation.case_id for facts in record.facts] == [
            "episode-1#0",
            "episode-1#1",
        ]
        assert all(facts.observation.replay_matches for facts in record.facts)
        assert all(
            turn.replay_outcome == "reproduced" for turn in record.transcript.turns
        )

    def test_t3_releases_nothing_and_sends_no_action(self, tmp_path: Path) -> None:
        client = RecordingTutor()
        record = _run(tmp_path, client, AbsentTutor(), _spec("T3", "open", 2, None))
        assert client.actions == []
        assert record.transcript.turns[0].released is None
        assert record.transcript.turns[0].decision == "none"
        action = record.facts[0].observation.action
        assert action is not None
        assert action.decision == "none"

    def test_s1_pauses_when_drift_fires_on_the_planned_turn(
        self, tmp_path: Path
    ) -> None:
        client = RecordingTutor(halt_on=1)
        record = _run(
            tmp_path, client, ComplacentTutor(), _spec("T2", "S1_drift", 3, 1)
        )
        assert record.transcript.turns[1].halted_at == "drift_and_anomaly"
        assert record.facts[1].observation.outcome == "held"

    def test_s1_aborts_when_the_planned_turn_does_not_drift(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(CampaignAbort, match="did not pause"):
            _run(
                tmp_path,
                RecordingTutor(),
                ComplacentTutor(),
                _spec("T2", "S1_drift", 3, 1),
            )

    def test_s2_stops_then_probes_once_and_rereads_every_turn_up_to_the_stop(
        self, tmp_path: Path
    ) -> None:
        client = RecordingTutor()
        record = _run(tmp_path, client, StoppingTutor(1), _spec("T4", "S2_stop", 4, 1))
        transcript = record.transcript
        assert transcript.stopped is True
        assert [turn.turn_index for turn in transcript.turns] == [0, 1]
        assert client.actions[-1] == "stop"
        assert len(client.prompts) == 3
        assert client.prompts[2] == client.prompts[1]
        turn_ids = [turn.turn_id for turn in transcript.turns]
        assert client.reads == turn_ids + turn_ids
        assert client.replays == turn_ids + turn_ids

    def test_s2_records_inv7_on_the_stop_turn_and_it_passes(
        self, tmp_path: Path
    ) -> None:
        record = _run(
            tmp_path, RecordingTutor(), StoppingTutor(1), _spec("T4", "S2_stop", 4, 1)
        )
        assert [facts.session_stopped for facts in record.facts] == [False, True]
        assert record.facts[1].later_turns_refused is True
        assert record.facts[1].earlier_turns_readable is True
        assert _inv7(record) == [True, True]

    def test_inv7_fails_when_the_api_accepts_a_turn_after_the_stop(
        self, tmp_path: Path
    ) -> None:
        client = RecordingTutor()
        client.refuse_after_stop = False
        record = _run(tmp_path, client, StoppingTutor(1), _spec("T4", "S2_stop", 4, 1))
        assert record.facts[1].later_turns_refused is False
        assert _inv7(record) == [True, False]

    def test_inv7_fails_when_a_turn_cannot_be_read_after_the_stop(
        self, tmp_path: Path
    ) -> None:
        record = _run(
            tmp_path,
            UnreadableAfterStop(),
            StoppingTutor(1),
            _spec("T4", "S2_stop", 4, 1),
        )
        assert record.facts[1].earlier_turns_readable is False
        assert _inv7(record) == [True, False]

    def test_a_stop_the_api_did_not_record_is_not_checked_as_a_stop(
        self, tmp_path: Path
    ) -> None:
        class RejectingStop(RecordingTutor):
            def act(
                self,
                session_id: UUID,
                turn_id: UUID,
                tutor_id: str,
                action: str,
                edited_output: str | None,
            ) -> ActionCall:
                self.actions.append(action)
                return ActionCall(http_status=409, kind="rejected", detail="no")

        client = RejectingStop()
        record = _run(tmp_path, client, StoppingTutor(0), _spec("T4", "S2_stop", 4, 0))
        assert record.transcript.stopped is True
        assert len(client.prompts) == 1
        assert [facts.session_stopped for facts in record.facts] == [False]

    def test_the_transcript_is_one_line_per_turn_at_the_episode_path(
        self, tmp_path: Path
    ) -> None:
        record = _run(
            tmp_path, RecordingTutor(), StoppingTutor(1), _spec("T4", "S2_stop", 4, 1)
        )
        path = tmp_path / "episode-1.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        assert [EpisodeTurn.model_validate_json(line) for line in lines] == list(
            record.transcript.turns
        )
        assert list(tmp_path.iterdir()) == [path]

    def test_the_transcript_is_written_when_the_episode_does_not_stop(
        self, tmp_path: Path
    ) -> None:
        _run(tmp_path, RecordingTutor(), AbsentTutor(), _spec("T3", "open", 2, None))
        lines = (tmp_path / "episode-1.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2

    def test_the_pupil_and_the_tutor_role_each_use_a_stubbed_model(
        self, tmp_path: Path
    ) -> None:
        pupil = ScriptedRoleModel("ab" * 32, "The pupil asks about habits.")
        tutor = ScriptedRoleModel("cd" * 32, "approve")
        record = _run(
            tmp_path,
            RecordingTutor(),
            DiligentTutor(tutor, "You approve a draft the dashboard shows."),
            _spec("T1", "open", 1, None),
            pupil=pupil,
        )
        turn = record.transcript.turns[0]
        assert turn.prompt == "The pupil asks about habits."
        assert turn.decision == "approve"
        assert turn.released == "release-0"

    def test_an_edit_releases_the_edited_text_and_the_pupil_reads_it(
        self, tmp_path: Path
    ) -> None:
        client = RecordingTutor()
        role = ScriptedDecisions(
            TutorDecision(decision="edit", edited_output="Corrected text"),
            TutorDecision(decision="approve"),
        )
        record = _run(tmp_path, client, role, _spec("T2", "open", 2, None))
        assert record.transcript.turns[0].released == "Corrected text"
        assert "Corrected text" in client.prompts[1]
        assert "release-0" not in client.prompts[1]
        assert record.facts[0].edit_accepted is True
        assert record.facts[1].edit_accepted is False

    def test_an_override_releases_nothing(self, tmp_path: Path) -> None:
        client = RecordingTutor()
        role = ScriptedDecisions(
            TutorDecision(decision="override"),
            TutorDecision(decision="approve"),
        )
        record = _run(tmp_path, client, role, _spec("T2", "open", 2, None))
        assert client.actions[0] == "override"
        assert record.transcript.turns[0].released is None
        assert "release-0" not in client.prompts[1]

    def test_the_injected_mode_guard_decides_whether_the_episode_runs(
        self, tmp_path: Path
    ) -> None:
        client = RecordingTutor()
        with pytest.raises(CampaignAbort, match="injected guard"):
            _run(
                tmp_path,
                client,
                ComplacentTutor(),
                _spec("T2", "open", 2, None),
                mode=RefusingMode(),
            )
        assert client.prompts == []

    def test_a_learner_the_seed_does_not_retain_opens_no_session(
        self, tmp_path: Path
    ) -> None:
        client = RecordingTutor()
        client.retained = ()
        with pytest.raises(CampaignAbort, match="not a retained persona"):
            _run(tmp_path, client, ComplacentTutor(), _spec("T2", "open", 2, None))
        assert client.opens == 0

    def test_an_unknown_turn_status_aborts(self, tmp_path: Path) -> None:
        client = RecordingTutor()
        client.status_override = "something_new"
        with pytest.raises(CampaignAbort, match="status something_new"):
            _run(tmp_path, client, ComplacentTutor(), _spec("T2", "open", 2, None))

    @pytest.mark.parametrize(
        ("failing", "message"),
        [
            ("learners", "roster could not be read"),
            ("open", "did not open"),
            ("submit", "was not accepted"),
            ("act", "was not recorded"),
            ("detail", "could not be read"),
            ("replay", "could not be replayed"),
            ("audit", "audit could not be read"),
        ],
    )
    def test_a_failed_call_while_the_episode_runs_aborts_it(
        self, tmp_path: Path, failing: str, message: str
    ) -> None:
        with pytest.raises(CampaignAbort, match=message):
            _run(
                tmp_path,
                FailingTutor(failing),
                ComplacentTutor(),
                _spec("T2", "open", 2, None),
            )
        assert not (tmp_path / "episode-1.jsonl").exists()


class TestEpisodePlanFile:
    def test_the_plan_round_trips_and_no_episodes_is_an_empty_file(
        self, tmp_path: Path
    ) -> None:
        plan = EpisodePlanFile()
        path = tmp_path / "plan.jsonl"
        assert plan.body(()) == b""
        specs = (_spec("T4", "S2_stop", 4, 1), _spec("T3", "open", 2, None))
        path.write_bytes(plan.body(specs))
        assert plan.read(path) == specs

    def test_a_missing_plan_is_a_command_error(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="no episode plan"):
            EpisodePlanFile().read(tmp_path / "plan.jsonl")


class TestTutorRoster:
    def test_a_role_is_found_by_its_own_name(self) -> None:
        stopping = StoppingTutor(3)
        roster = TutorRoster((ComplacentTutor(), AbsentTutor(), stopping))
        assert roster.role("T4") is stopping

    def test_an_unknown_role_is_refused(self) -> None:
        with pytest.raises(UnknownTutorRole, match="no tutor role T1"):
            TutorRoster((AbsentTutor(),)).role("T1")

    def test_two_roles_with_one_name_are_refused(self) -> None:
        with pytest.raises(ValueError, match="share a name"):
            TutorRoster((AbsentTutor(), AbsentTutor()))
