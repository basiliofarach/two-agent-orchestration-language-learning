"""An interrupted Tier 2 run resumes with ``SIM_RUN_ID`` (SIMULATION §8.3).

The real command, dataset store, manifest, runner, trail file, oracle and
run directory are wired; only the tutor API and the role model are stubbed.
A resumed run submits only the episodes its trail does not hold, and its
report counts the invariant rows of every episode, old and new.
"""

import io
import json
from pathlib import Path
from uuid import UUID

from tests.integration.test_episode_campaign import _client, _commands, _episode, _plan
from tests.unit.sim.test_episode_runner import RecordingTutor
from tests.unit.sim.test_episode_trail import RefusesTurn
from tests.unit.sim.test_kernel import OfflineSettings

from tutor_sim.domain.models.client_call import TurnCall
from tutor_sim.domain.models.identity import SimulationNamespace
from tutor_sim.domain.models.report import SimulationReport
from tutor_sim.settings import SimulationSettings

_RUN = "run-20261104T120000"
_EPISODES = (
    _episode("e-one", "T2", "open", None),
    _episode("e-two", "T2", "open", None),
    _episode("e-three", "T2", "open", None),
)


class FailsAfter(RecordingTutor):
    """Accepts ``limit`` submits, then answers 503 to every later one."""

    def __init__(self, limit: int) -> None:
        super().__init__()
        self._limit = limit

    def submit(
        self,
        session_id: UUID,
        learner_id: UUID,
        prompt: str,
        fields: tuple[str, ...],
    ) -> TurnCall:
        if len(self.prompts) >= self._limit:
            return TurnCall(http_status=503, kind="errored", detail="ReadTimeout")
        return super().submit(session_id, learner_id, prompt, fields)


def _ready(tmp_path: Path) -> SimulationSettings:
    settings = OfflineSettings().build(tmp_path, True)
    _plan(settings, _EPISODES)
    commands = _commands(settings, _client(), io.StringIO())
    assert commands.dispatch("pupil-messages") == 0
    assert commands.dispatch("freeze") == 0
    return settings


def _retained(client: RecordingTutor) -> RecordingTutor:
    client.retained = (SimulationNamespace().learner_id("p-a2-es-12_14-01"),)
    client.policy = "prototype-2"
    return client


def _aborted(settings: SimulationSettings, errors: io.StringIO) -> Path:
    """Two episodes of three turns finish; the third fails on its first turn."""
    commands = _commands(settings, _retained(FailsAfter(6)), errors)
    assert commands.dispatch("episodes") == 1
    return settings.evidence_dir / "runs" / _RUN


def _resumed(settings: SimulationSettings) -> SimulationSettings:
    return settings.model_copy(update={"run_id": _RUN})


def _report(run: Path) -> SimulationReport:
    return SimulationReport.model_validate_json(
        (run / "report.json").read_text(encoding="utf-8")
    )


def test_an_aborted_tier_2_run_keeps_its_finished_episodes(tmp_path: Path) -> None:
    errors = io.StringIO()
    run = _aborted(_ready(tmp_path), errors)
    lines = (run / "episodes.jsonl").read_text("utf-8").splitlines()
    assert [json.loads(line)["episode_id"] for line in lines] == ["e-one", "e-two"]
    assert not (run / "report.json").exists()
    assert f"SIM_RUN_ID={_RUN}" in errors.getvalue()


def test_a_resumed_run_submits_only_the_unfinished_episodes(tmp_path: Path) -> None:
    settings = _ready(tmp_path)
    run = _aborted(settings, io.StringIO())
    client = _retained(RecordingTutor())
    errors = io.StringIO()
    commands = _commands(_resumed(settings), client, errors)
    assert commands.dispatch("episodes") == 0, errors.getvalue()
    assert client.opens == 1
    assert len(client.prompts) == 3
    assert "resuming run-20261104T120000: 2 of 3 episodes" in errors.getvalue()
    report = _report(run)
    assert report.run_id == _RUN
    assert len(report.invariants) == 8 * (3 + 3 + 3)
    assert report.finished is True
    assert (run / "transcripts" / "e-three.jsonl").is_file()


def test_a_finished_tier_2_run_is_not_resumed(tmp_path: Path) -> None:
    settings = _ready(tmp_path)
    run = _aborted(settings, io.StringIO())
    resumed = _resumed(settings)
    assert (
        _commands(resumed, _retained(RecordingTutor()), io.StringIO()).dispatch(
            "episodes"
        )
        == 0
    )
    errors = io.StringIO()
    client = _retained(RecordingTutor())
    assert _commands(resumed, client, errors).dispatch("episodes") == 1
    assert "already finished" in errors.getvalue()
    assert client.prompts == []
    assert (run / "report.json").is_file()


def test_a_run_without_an_episode_trail_is_not_resumed(tmp_path: Path) -> None:
    settings = _ready(tmp_path)
    (settings.evidence_dir / "runs" / _RUN).mkdir(parents=True)
    errors = io.StringIO()
    client = _retained(RecordingTutor())
    assert _commands(_resumed(settings), client, errors).dispatch("episodes") == 1
    assert "has no episodes to resume" in errors.getvalue()
    assert client.prompts == []


def test_a_trail_naming_an_episode_outside_the_plan_is_not_resumed(
    tmp_path: Path,
) -> None:
    settings = _ready(tmp_path)
    run = _aborted(settings, io.StringIO())
    with (run / "episodes.jsonl").open("a", encoding="utf-8") as handle:
        handle.write('{"episode_id": "e-elsewhere", "facts": []}\n')
    errors = io.StringIO()
    assert (
        _commands(_resumed(settings), _retained(RecordingTutor()), errors).dispatch(
            "episodes"
        )
        == 1
    )
    assert "e-elsewhere is not in the frozen episode plan" in errors.getvalue()


def test_a_cut_off_trail_line_is_dropped_and_that_episode_reruns(
    tmp_path: Path,
) -> None:
    settings = _ready(tmp_path)
    run = _aborted(settings, io.StringIO())
    trail = run / "episodes.jsonl"
    kept = trail.read_text("utf-8").splitlines()
    trail.write_text(kept[0] + "\n" + kept[1][:20], encoding="utf-8")
    client = _retained(RecordingTutor())
    errors = io.StringIO()
    assert _commands(_resumed(settings), client, errors).dispatch("episodes") == 0
    assert "dropped an unfinished last line" in errors.getvalue()
    assert client.opens == 2
    assert len(_report(run).invariants) == 8 * 9


def test_a_damaged_trail_is_not_resumed(tmp_path: Path) -> None:
    settings = _ready(tmp_path)
    run = _aborted(settings, io.StringIO())
    trail = run / "episodes.jsonl"
    trail.write_text("{}\n" + trail.read_text("utf-8"), encoding="utf-8")
    errors = io.StringIO()
    assert (
        _commands(_resumed(settings), _retained(RecordingTutor()), errors).dispatch(
            "episodes"
        )
        == 1
    )
    assert "damaged" in errors.getvalue()


def test_a_refused_message_is_reported_and_the_run_finishes(tmp_path: Path) -> None:
    settings = _ready(tmp_path)
    errors = io.StringIO()
    commands = _commands(settings, _retained(RefusesTurn(1)), errors)
    assert commands.dispatch("episodes") == 0, errors.getvalue()
    message = errors.getvalue()
    assert "e-one ended at turn 1: the API refused the pupil's message" in message
    assert "HTTP 422 session_rejected" in message
    run = settings.evidence_dir / "runs" / _RUN
    lines = [
        json.loads(line)
        for line in (run / "episodes.jsonl").read_text("utf-8").splitlines()
    ]
    assert lines[0]["rejected"]["turn_index"] == 1
    assert lines[1]["rejected"] is None
    report = _report(run)
    assert len(report.invariants) == 8 * (1 + 3 + 3)
