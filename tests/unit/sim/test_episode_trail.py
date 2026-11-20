"""A refused pupil message ends its episode; each episode leaves a trail line.

At temperature 0 the role model writes the same message every time, so a
message the API refuses (HTTP 422, e.g. over the 2000-character prompt
bound) would refuse again on every rerun. The refusal is the system
behaving as specified, so it is recorded and the episode ends there. Every
other failed call still aborts the campaign.

``episodes.jsonl`` holds one line per finished episode: its invariant
facts, which the report needs and the transcripts do not carry, so an
interrupted Tier 2 run can be resumed.
"""

from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError
from tests.unit.sim.test_episode_runner import RecordingTutor, _run, _spec

from tutor_sim.application.commands import DamagedCampaign, EpisodeTrailFile
from tutor_sim.application.episode import EpisodeLine
from tutor_sim.application.roles import ComplacentTutor
from tutor_sim.domain.models.client_call import TurnCall
from tutor_sim.domain.models.episode import RejectedPrompt

_REFUSED = RejectedPrompt(
    turn_index=1, characters=2400, http_status=422, kind="session_rejected"
)


class RefusesTurn(RecordingTutor):
    """Refuses the submit at ``index`` with 422, as the prompt bound does."""

    def __init__(self, index: int) -> None:
        super().__init__()
        self._refuse = index

    def submit(
        self,
        session_id: UUID,
        learner_id: UUID,
        prompt: str,
        fields: tuple[str, ...],
    ) -> TurnCall:
        if len(self.prompts) == self._refuse:
            self.prompts.append(prompt)
            return TurnCall(
                http_status=422,
                kind="session_rejected",
                detail="String should have at most 2000 characters",
            )
        return super().submit(session_id, learner_id, prompt, fields)


class TestRefusedMessage:
    def test_a_refused_message_ends_the_episode_and_is_recorded(
        self, tmp_path: Path
    ) -> None:
        client = RefusesTurn(1)
        record = _run(tmp_path, client, ComplacentTutor(), _spec("T2", "open", 4, None))
        assert len(record.transcript.turns) == 1
        assert record.transcript.stopped is False
        assert record.rejected is not None
        assert record.rejected.turn_index == 1
        assert record.rejected.characters == len(client.prompts[1])
        assert record.rejected.http_status == 422
        assert len(client.prompts) == 2

    def test_the_refused_message_gets_no_tutor_action_and_no_observation(
        self, tmp_path: Path
    ) -> None:
        client = RefusesTurn(1)
        record = _run(tmp_path, client, ComplacentTutor(), _spec("T2", "open", 4, None))
        assert client.actions == ["approve"]
        assert len(record.facts) == 1

    def test_the_transcript_of_a_refused_episode_is_still_written(
        self, tmp_path: Path
    ) -> None:
        _run(tmp_path, RefusesTurn(1), ComplacentTutor(), _spec("T2", "open", 4, None))
        lines = (tmp_path / "episode-1.jsonl").read_text("utf-8").splitlines()
        assert len(lines) == 1

    def test_an_episode_with_no_refusal_records_none(self, tmp_path: Path) -> None:
        record = _run(
            tmp_path, RecordingTutor(), ComplacentTutor(), _spec("T2", "open", 2, None)
        )
        assert record.rejected is None


class TestTrailModels:
    def test_a_refused_message_is_frozen_and_closed(self) -> None:
        with pytest.raises(ValidationError):
            _REFUSED.characters = 1  # type: ignore[misc]
        with pytest.raises(ValidationError):
            RejectedPrompt.model_validate(
                {**_REFUSED.model_dump(), "prompt": "the text is not kept"}
            )
        with pytest.raises(ValidationError):
            RejectedPrompt(
                turn_index=8, characters=1, http_status=422, kind="session_rejected"
            )

    def test_an_episode_line_is_frozen_and_closed(self) -> None:
        line = EpisodeLine(episode_id="e-1", facts=())
        assert line.rejected is None
        with pytest.raises(ValidationError):
            line.episode_id = "e-2"  # type: ignore[misc]
        with pytest.raises(ValidationError):
            EpisodeLine.model_validate({"episode_id": "e-1", "facts": [], "x": 1})
        with pytest.raises(ValidationError):
            EpisodeLine(episode_id="", facts=())


class TestEpisodeTrailFile:
    def test_lines_append_and_recover_in_order(self, tmp_path: Path) -> None:
        path = tmp_path / "episodes.jsonl"
        trail = EpisodeTrailFile()
        trail.write(path, ())
        trail.append(path, EpisodeLine(episode_id="e-1", facts=()))
        trail.append(path, EpisodeLine(episode_id="e-2", facts=(), rejected=_REFUSED))
        recovered = trail.recover(path)
        assert [line.episode_id for line in recovered.lines] == ["e-1", "e-2"]
        assert recovered.lines[1].rejected == _REFUSED
        assert recovered.dropped is False

    def test_a_cut_off_last_line_is_dropped_and_the_file_rewritten(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "episodes.jsonl"
        trail = EpisodeTrailFile()
        trail.write(path, (EpisodeLine(episode_id="e-1", facts=()),))
        with path.open("a", encoding="utf-8") as handle:
            handle.write('{"episode_id": "e-2", "fac')
        recovered = trail.recover(path)
        assert [line.episode_id for line in recovered.lines] == ["e-1"]
        assert recovered.dropped is True
        assert path.read_text("utf-8").endswith("}\n")

    def test_a_damaged_line_before_the_last_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "episodes.jsonl"
        path.write_text('{"broken": true}\n{"episode_id": "e-1", "facts": []}\n')
        with pytest.raises(DamagedCampaign):
            EpisodeTrailFile().recover(path)
