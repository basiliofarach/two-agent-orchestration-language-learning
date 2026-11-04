"""Tier 2: the pupil reads a release, a stop ends the episode, eight is the cap."""

from uuid import UUID

import pytest
from pydantic import ValidationError

from tutor_sim.adapters.role_model import EchoRoleModel
from tutor_sim.application.episode import EpisodeRunner
from tutor_sim.application.roles import AbsentTutor, ComplacentTutor, StoppingTutor
from tutor_sim.application.tier1 import CampaignAbort
from tutor_sim.domain.models.api_views import HealthView, SessionView, TurnOutcomeView
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
from tutor_sim.domain.ports.tutor_client import TutorClientPort

_LEARNER = UUID(int=2)
_SESSION = UUID(int=3)


class RecordingTutor(TutorClientPort):
    """Counts submits and actions. The reply is the turn index."""

    def __init__(self, halt_on: int | None = None) -> None:
        self.prompts: list[str] = []
        self.actions: list[str] = []
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
        raise NotImplementedError

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
        raise NotImplementedError


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
        transcript = EpisodeRunner(client, ComplacentTutor(), EchoRoleModel()).run(
            _spec("T2", "open", 3, None), _LEARNER, "tutor", "You are a learner."
        )
        assert len(transcript.turns) == 3
        assert transcript.stopped is False
        assert "release-0" in client.prompts[1]
        assert transcript.turns[0].released == "release-0"

    def test_t3_releases_nothing(self) -> None:
        client = RecordingTutor()
        transcript = EpisodeRunner(client, AbsentTutor(), EchoRoleModel()).run(
            _spec("T3", "open", 2, None), _LEARNER, "tutor", "You are a learner."
        )
        assert client.actions == []
        assert transcript.turns[0].released is None
        assert transcript.turns[0].decision == "none"

    def test_s1_pauses_when_drift_fires_on_the_planned_turn(self) -> None:
        client = RecordingTutor(halt_on=1)
        transcript = EpisodeRunner(client, ComplacentTutor(), EchoRoleModel()).run(
            _spec("T2", "S1_drift", 3, 1), _LEARNER, "tutor", "You are a learner."
        )
        assert transcript.turns[1].halted_at == "drift_and_anomaly"

    def test_s1_aborts_when_the_planned_turn_does_not_drift(self) -> None:
        client = RecordingTutor()
        with pytest.raises(CampaignAbort, match="did not pause"):
            EpisodeRunner(client, ComplacentTutor(), EchoRoleModel()).run(
                _spec("T2", "S1_drift", 3, 1),
                _LEARNER,
                "tutor",
                "You are a learner.",
            )

    def test_s2_stops_and_does_not_submit_the_later_turns(self) -> None:
        client = RecordingTutor()
        transcript = EpisodeRunner(client, StoppingTutor(1), EchoRoleModel()).run(
            _spec("T4", "S2_stop", 4, 1), _LEARNER, "tutor", "You are a learner."
        )
        assert transcript.stopped is True
        assert [turn.turn_index for turn in transcript.turns] == [0, 1]
        assert client.actions[-1] == "stop"
        assert len(client.prompts) == 2
