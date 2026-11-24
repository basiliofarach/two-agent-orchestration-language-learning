"""The pupil answers what reached it, and follows up when nothing did.

The first campaign sent the pupil ``"Begin the lesson."`` whenever nothing
was released. At temperature 0 it then wrote the same message every turn.
"""

from pathlib import Path

from tests.unit.sim.test_episode_runner import RecordingTutor, _run, _spec

from tutor_sim.application.episode import PupilTurnBrief
from tutor_sim.application.roles import AbsentTutor, ComplacentTutor
from tutor_sim.domain.ports.role_model import RoleModelPort


class Pupil(RoleModelPort):
    """Writes ``message-<n>`` padded with spaces, and records each ask."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def weights_sha(self) -> str:
        return "ab" * 32

    def complete(self, system: str, user: str) -> str:
        self.asked.append(user)
        return f"  message-{len(self.asked)}\n"


class TestPupilTurnBrief:
    def test_the_first_turn_opens_the_lesson(self) -> None:
        assert PupilTurnBrief().render(None, None).startswith("Begin the lesson.")

    def test_a_released_reply_is_shown_to_the_pupil(self) -> None:
        text = PupilTurnBrief().render("Use 'kick'.", "Help me with verbs")
        assert "Your tutor replied:\n\nUse 'kick'." in text
        assert "Help me with verbs" not in text

    def test_silence_shows_the_pupil_its_own_last_message(self) -> None:
        text = PupilTurnBrief().render(None, "Help me with verbs")
        assert "has not answered" in text
        assert "Help me with verbs" in text
        assert "Do not repeat" in text


class TestEpisodePupil:
    def test_an_absent_tutor_makes_the_pupil_follow_up(self, tmp_path: Path) -> None:
        pupil = Pupil()
        client = RecordingTutor()
        _run(tmp_path, client, AbsentTutor(), _spec("T3", "open", 3, None), pupil)
        assert pupil.asked[0].startswith("Begin the lesson.")
        assert "has not answered" in pupil.asked[1]
        assert "message-1" in pupil.asked[1]
        assert "message-2" in pupil.asked[2]

    def test_a_released_reply_is_what_the_pupil_answers(self, tmp_path: Path) -> None:
        pupil = Pupil()
        client = RecordingTutor()
        _run(tmp_path, client, ComplacentTutor(), _spec("T2", "open", 2, None), pupil)
        assert "Your tutor replied:\n\nrelease-0" in pupil.asked[1]

    def test_the_pupil_message_is_sent_trimmed(self, tmp_path: Path) -> None:
        client = RecordingTutor()
        _run(tmp_path, client, AbsentTutor(), _spec("T3", "open", 2, None), Pupil())
        assert client.prompts[:2] == ["message-1", "message-2"]
