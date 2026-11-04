"""Tier 2: the pupil reads a release, a stop ends the episode, eight is the cap."""

from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from tutor_sim.adapters.role_model import EchoRoleModel, ScriptedRoleModel
from tutor_sim.application.episode import EpisodeArchive, EpisodeRunner
from tutor_sim.application.roles import (
    AbsentTutor,
    ComplacentTutor,
    DiligentTutor,
    StoppingTutor,
)
from tutor_sim.application.tier1 import CampaignAbort, ModeGuard
from tutor_sim.domain.models.api_views import (
    HealthView,
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
from tutor_sim.domain.models.tutor_role import DashboardView, TutorDecision
from tutor_sim.domain.ports.tutor_client import TutorClientPort
from tutor_sim.domain.ports.tutor_role import TutorRolePort

_LEARNER = UUID(int=2)
_SESSION = UUID(int=3)


class RecordingTutor(TutorClientPort):
    """Counts submits and actions. The reply is the turn index."""

    def __init__(self, halt_on: int | None = None) -> None:
        self.prompts: list[str] = []
        self.actions: list[str] = []
        self.reads: list[UUID] = []
        self.replays: list[UUID] = []
        self._halt_on = halt_on

    def health(self) -> HealthCall:
        return HealthCall(
            http_status=200,
            kind="ok",
            body=HealthView(status="ok", database_configured=True, mode="simulation"),
        )

    def learners(self) -> LearnerCall:
        raise NotImplementedError

    def open_session(self, learner_id: UUID, tutor_id: str) -> SessionCall:
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
        halted = "drift_and_anomaly" if index == self._halt_on else None
        return TurnCall(
            http_status=200,
            kind="ok",
            body=TurnOutcomeView(
                turn_id=UUID(int=10 + index),
                session_id=session_id,
                status="held_for_review" if halted else "awaiting_tutor_approval",
                halted_at=halted,
                refused=False,
                policy_version="sim-1",
                reply=f"release-{index}",
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
        return ActionCall(http_status=200, kind="ok")

    def audit(self, session_id: UUID) -> AuditCall:
        raise NotImplementedError

    def replay(self, turn_id: UUID) -> ReplayCall:
        self.replays.append(turn_id)
        return ReplayCall(
            http_status=200,
            kind="ok",
            body=ReplayView(turn_id=turn_id, outcome="reproduced"),
        )


class UnreadableEarlierTurn(RecordingTutor):
    """The stop is recorded, then an earlier turn cannot be read or replayed."""

    def __init__(self, failing: str) -> None:
        super().__init__()
        self._failing = failing

    def detail(self, turn_id: UUID) -> DetailCall:
        if self._failing == "detail":
            return DetailCall(http_status=503, kind="errored")
        return super().detail(turn_id)

    def replay(self, turn_id: UUID) -> ReplayCall:
        if self._failing == "replay":
            return ReplayCall(http_status=503, kind="errored")
        return super().replay(turn_id)


class FailingTutor(RecordingTutor):
    """Fails one call — ``open``, ``submit`` or ``act`` — with a 503."""

    def __init__(self, failing: str) -> None:
        super().__init__()
        self._failing = failing

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


class ScriptedDecisions(TutorRolePort):
    """Returns the given decisions in order, one per held turn."""

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


class TestEpisodeRunner:
    def test_eight_turns_is_the_model_cap(self) -> None:
        with pytest.raises(ValidationError):
            _spec("T2", "open", 9, None)

    def test_an_open_episode_submits_every_turn_and_the_pupil_reads_the_release(
        self,
    ) -> None:
        client = RecordingTutor()
        transcript = EpisodeRunner(
            client, ComplacentTutor(), EchoRoleModel(), ModeGuard()
        ).run(_spec("T2", "open", 3, None), _LEARNER, "tutor", "You are a learner.")
        assert len(transcript.turns) == 3
        assert transcript.stopped is False
        assert "release-0" in client.prompts[1]
        assert transcript.turns[0].released == "release-0"

    def test_t3_releases_nothing(self) -> None:
        client = RecordingTutor()
        transcript = EpisodeRunner(
            client, AbsentTutor(), EchoRoleModel(), ModeGuard()
        ).run(_spec("T3", "open", 2, None), _LEARNER, "tutor", "You are a learner.")
        assert client.actions == []
        assert transcript.turns[0].released is None
        assert transcript.turns[0].decision == "none"

    def test_s1_pauses_when_drift_fires_on_the_planned_turn(self) -> None:
        client = RecordingTutor(halt_on=1)
        transcript = EpisodeRunner(
            client, ComplacentTutor(), EchoRoleModel(), ModeGuard()
        ).run(_spec("T2", "S1_drift", 3, 1), _LEARNER, "tutor", "You are a learner.")
        assert transcript.turns[1].halted_at == "drift_and_anomaly"

    def test_s1_aborts_when_the_planned_turn_does_not_drift(self) -> None:
        client = RecordingTutor()
        with pytest.raises(CampaignAbort, match="did not pause"):
            EpisodeRunner(client, ComplacentTutor(), EchoRoleModel(), ModeGuard()).run(
                _spec("T2", "S1_drift", 3, 1),
                _LEARNER,
                "tutor",
                "You are a learner.",
            )

    def test_s2_stops_and_does_not_submit_the_later_turns(self) -> None:
        client = RecordingTutor()
        transcript = EpisodeRunner(
            client, StoppingTutor(1), EchoRoleModel(), ModeGuard()
        ).run(_spec("T4", "S2_stop", 4, 1), _LEARNER, "tutor", "You are a learner.")
        assert transcript.stopped is True
        assert [turn.turn_index for turn in transcript.turns] == [0, 1]
        assert client.actions[-1] == "stop"
        assert len(client.prompts) == 2
        assert client.reads == [transcript.turns[0].turn_id]
        assert client.replays == client.reads
        assert transcript.turns[0].replay_outcome == "reproduced"
        assert transcript.turns[1].replay_outcome is None

    def test_a_stop_writes_the_transcript_beside_the_run(self, tmp_path: Path) -> None:
        client = RecordingTutor()
        archive = EpisodeArchive(tmp_path)
        transcript = EpisodeRunner(
            client, StoppingTutor(1), EchoRoleModel(), ModeGuard(), archive
        ).run(_spec("T4", "S2_stop", 4, 1), _LEARNER, "tutor", "You are a learner.")
        written = (tmp_path / "episode-1.json").read_text(encoding="utf-8")
        assert transcript.episode_id in written
        assert '"replay_outcome": "reproduced"' in written

    def test_a_stop_aborts_when_an_earlier_turn_cannot_be_read(self) -> None:
        client = UnreadableEarlierTurn("detail")
        with pytest.raises(CampaignAbort, match="could not be read"):
            EpisodeRunner(client, StoppingTutor(1), EchoRoleModel(), ModeGuard()).run(
                _spec("T4", "S2_stop", 4, 1), _LEARNER, "tutor", "You are a learner."
            )

    def test_a_stop_aborts_when_an_earlier_turn_cannot_be_replayed(self) -> None:
        client = UnreadableEarlierTurn("replay")
        with pytest.raises(CampaignAbort, match="could not be replayed"):
            EpisodeRunner(client, StoppingTutor(1), EchoRoleModel(), ModeGuard()).run(
                _spec("T4", "S2_stop", 4, 1), _LEARNER, "tutor", "You are a learner."
            )

    def test_the_pupil_and_the_tutor_role_each_use_a_stubbed_model(self) -> None:
        client = RecordingTutor()
        pupil = ScriptedRoleModel("ab" * 32, "The pupil asks about habits.")
        tutor = ScriptedRoleModel("cd" * 32, "approve")
        transcript = EpisodeRunner(
            client,
            DiligentTutor(tutor, "You approve a draft the dashboard shows."),
            pupil,
            ModeGuard(),
        ).run(_spec("T1", "open", 1, None), _LEARNER, "tutor", "You are a learner.")
        assert transcript.turns[0].prompt == "The pupil asks about habits."
        assert transcript.turns[0].decision == "approve"
        assert transcript.turns[0].released == "release-0"

    def test_an_edit_releases_the_edited_text_and_the_pupil_reads_it(
        self,
    ) -> None:
        client = RecordingTutor()
        role = ScriptedDecisions(
            TutorDecision(decision="edit", edited_output="Corrected text"),
            TutorDecision(decision="approve"),
        )
        transcript = EpisodeRunner(client, role, EchoRoleModel(), ModeGuard()).run(
            _spec("T2", "open", 2, None), _LEARNER, "tutor", "You are a learner."
        )
        assert transcript.turns[0].released == "Corrected text"
        assert "Corrected text" in client.prompts[1]
        assert "release-0" not in client.prompts[1]

    def test_an_override_releases_nothing(self) -> None:
        client = RecordingTutor()
        role = ScriptedDecisions(
            TutorDecision(decision="override"),
            TutorDecision(decision="approve"),
        )
        transcript = EpisodeRunner(client, role, EchoRoleModel(), ModeGuard()).run(
            _spec("T2", "open", 2, None), _LEARNER, "tutor", "You are a learner."
        )
        assert client.actions[0] == "override"
        assert transcript.turns[0].released is None
        assert "release-0" not in client.prompts[1]

    def test_the_injected_mode_guard_decides_whether_the_episode_runs(
        self,
    ) -> None:
        client = RecordingTutor()
        runner = EpisodeRunner(
            client, ComplacentTutor(), EchoRoleModel(), RefusingMode()
        )
        with pytest.raises(CampaignAbort, match="injected guard"):
            runner.run(
                _spec("T2", "open", 2, None), _LEARNER, "tutor", "You are a learner."
            )
        assert client.prompts == []

    @pytest.mark.parametrize(
        ("failing", "message"),
        [
            ("open", "did not open"),
            ("submit", "was not accepted"),
            ("act", "was not recorded"),
        ],
    )
    def test_a_refused_call_aborts_the_episode(
        self, failing: str, message: str
    ) -> None:
        runner = EpisodeRunner(
            FailingTutor(failing), ComplacentTutor(), EchoRoleModel(), ModeGuard()
        )
        with pytest.raises(CampaignAbort, match=message):
            runner.run(
                _spec("T2", "open", 2, None), _LEARNER, "tutor", "You are a learner."
            )
