"""The episode runner wired to the scripted roles and the echo pupil."""

from uuid import UUID

from tests.unit.sim.test_episode_runner import RecordingTutor, _spec

from tutor_sim.adapters.role_model import EchoRoleModel
from tutor_sim.application.episode import EpisodeRunner
from tutor_sim.application.roles import StoppingTutor
from tutor_sim.application.tier1 import ModeGuard


def test_a_stopping_tutor_ends_the_episode_before_the_cap() -> None:
    client = RecordingTutor()
    transcript = EpisodeRunner(
        client, StoppingTutor(0), EchoRoleModel(), ModeGuard()
    ).run(
        _spec("T4", "S2_stop", 8, 0),
        UUID(int=2),
        "tutor",
        "You are a learner.",
    )
    assert transcript.stopped is True
    assert len(transcript.turns) == 1
    assert len(client.prompts) == 1
