"""Tier 2 through the operator command: realise, freeze, then ``episodes``.

The real dataset store, manifest, roster, runner, oracle and run directory
are wired; only the tutor API and the role model are stubbed.
"""

import io
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from tests.unit.sim.test_episode_runner import RecordingTutor, _spec
from tests.unit.sim.test_kernel import OfflineSettings, PinnedSource
from tests.unit.sim.test_simulation_campaign import _case

from tutor_sim.adapters.file_dataset_store import FileDatasetStore
from tutor_sim.adapters.frozen_clock import FrozenClock
from tutor_sim.adapters.role_model import EchoRoleModel
from tutor_sim.application.commands import CampaignCommands
from tutor_sim.application.episode import EpisodeRunner, TranscriptFile
from tutor_sim.application.realise import RealisePlan
from tutor_sim.application.roles import (
    AbsentTutor,
    ComplacentTutor,
    StoppingTutor,
    TutorRoster,
)
from tutor_sim.application.tier1 import ModeGuard
from tutor_sim.cli import SimulationCli
from tutor_sim.composition import SimulationCompositionRoot
from tutor_sim.domain.models.case import EpisodeSpec
from tutor_sim.domain.models.episode import EpisodeTurn
from tutor_sim.domain.models.identity import SimulationNamespace
from tutor_sim.domain.models.report import RunSummary, SimulationReport
from tutor_sim.settings import SimulationSettings

_WHEN = datetime(2026, 11, 4, 12, tzinfo=UTC)
_PERSONA = "p-a2-es-12_14-01"


def _episode(episode_id: str, role: str, script: str, stop: int | None) -> EpisodeSpec:
    return _spec(role, script, 3, stop).model_copy(
        update={"episode_id": episode_id, "persona_id": _PERSONA}
    )


def _plan(settings: SimulationSettings, episodes: tuple[EpisodeSpec, ...]) -> None:
    plan = RealisePlan(
        dataset_version="sim-dataset/0.1.0",
        policy_version="prototype-2",
        seed=1,
        cases=(_case(),),
        episodes=episodes,
    )
    settings.dataset_dir.mkdir(parents=True, exist_ok=True)
    (settings.dataset_dir / "plan.json").write_text(
        plan.model_dump_json(), encoding="utf-8"
    )


def _commands(
    settings: SimulationSettings, client: RecordingTutor | None, errors: io.StringIO
) -> CampaignCommands:
    return CampaignCommands(
        settings,
        FrozenClock(_WHEN),
        FileDatasetStore(settings.dataset_dir),
        EchoRoleModel(),
        (PinnedSource().record(),),
        client,
        AbsentTutor(),
        TutorRoster((ComplacentTutor(), AbsentTutor(), StoppingTutor(1))),
        errors,
    )


def _client() -> RecordingTutor:
    client = RecordingTutor()
    client.retained = (SimulationNamespace().learner_id(_PERSONA),)
    client.policy = "prototype-2"
    return client


def test_a_stopping_tutor_ends_the_episode_before_the_cap(tmp_path: Path) -> None:
    client = RecordingTutor()
    record = EpisodeRunner(
        client, StoppingTutor(0), EchoRoleModel(), ModeGuard(), TranscriptFile(tmp_path)
    ).run(
        _spec("T4", "S2_stop", 8, 0),
        UUID(int=2),
        "tutor",
        "You are a learner.",
        "sim-1",
    )
    assert record.transcript.stopped is True
    assert len(record.transcript.turns) == 1
    assert len(client.prompts) == 2


def test_the_episodes_command_writes_a_tier_2_run_with_transcripts(
    tmp_path: Path,
) -> None:
    settings = OfflineSettings().build(tmp_path, True)
    episodes = (
        _episode("e-stop", "T4", "S2_stop", 1),
        _episode("e-absent", "T3", "open", None),
        _episode("e-complacent", "T2", "open", None),
    )
    _plan(settings, episodes)
    errors = io.StringIO()
    commands = _commands(settings, _client(), errors)
    assert commands.dispatch("realise") == 0
    assert commands.dispatch("freeze") == 0
    manifest = json.loads(
        (settings.dataset_dir / "public" / "manifest.json").read_text(encoding="utf-8")
    )
    assert "episodes/plan.jsonl" in [item["path"] for item in manifest["files"]]
    assert commands.dispatch("episodes") == 0, errors.getvalue()

    run = sorted((settings.evidence_dir / "runs").iterdir())[-1]
    summary = RunSummary.model_validate_json(
        (run / "summary.json").read_text(encoding="utf-8")
    )
    report = SimulationReport.model_validate_json(
        (run / "report.json").read_text(encoding="utf-8")
    )
    assert summary.tier == "2"
    assert summary.complete is True
    assert report.finished is True
    assert summary.passed_invariants is True
    assert report.label == "simulated:sim-dataset/0.1.0"
    assert [(row.name, row.n) for row in report.rates] == [
        ("headline_accuracy", 0),
        ("output_dependent", 0),
    ]
    # Two turns for the stop, three each for the open episodes: 8 rows per turn.
    assert len(report.invariants) == 8 * (2 + 3 + 3)
    transcripts = run / "transcripts"
    assert sorted(path.name for path in transcripts.iterdir()) == [
        "e-absent.jsonl",
        "e-complacent.jsonl",
        "e-stop.jsonl",
    ]
    stop = [
        EpisodeTurn.model_validate_json(line)
        for line in (transcripts / "e-stop.jsonl").read_text("utf-8").splitlines()
    ]
    assert [turn.decision for turn in stop] == ["approve", "stop"]


def test_an_api_that_accepts_a_turn_after_the_stop_fails_the_tier_2_run(
    tmp_path: Path,
) -> None:
    settings = OfflineSettings().build(tmp_path, True)
    _plan(settings, (_episode("e-stop", "T4", "S2_stop", 1),))
    client = _client()
    client.refuse_after_stop = False
    commands = _commands(settings, client, io.StringIO())
    assert commands.dispatch("realise") == 0
    assert commands.dispatch("freeze") == 0
    assert commands.dispatch("episodes") == 0
    run = sorted((settings.evidence_dir / "runs").iterdir())[-1]
    report = SimulationReport.model_validate_json(
        (run / "report.json").read_text(encoding="utf-8")
    )
    failed = [row.invariant_id for row in report.invariants if not row.passed]
    assert failed == ["INV-7"]
    assert report.finished is False


def test_a_source_every_turn_cites_is_counted_once_and_keeps_licence_pending(
    tmp_path: Path,
) -> None:
    settings = OfflineSettings().build(tmp_path, True)
    _plan(settings, (_episode("e-open", "T2", "open", None),))
    client = _client()
    client.sources = ("ellipse",)
    commands = _commands(settings, client, io.StringIO())
    assert commands.dispatch("realise") == 0
    assert commands.dispatch("freeze") == 0
    assert commands.dispatch("episodes") == 0
    run = sorted((settings.evidence_dir / "runs").iterdir())[-1]
    report = SimulationReport.model_validate_json(
        (run / "report.json").read_text(encoding="utf-8")
    )
    assert report.licence_status == "pending"
    assert report.pending_sources == ("ellipse",)


def test_a_tree_frozen_before_episodes_existed_has_no_episode_plan(
    tmp_path: Path,
) -> None:
    settings = OfflineSettings().build(tmp_path, True)
    _plan(settings, (_episode("e-open", "T2", "open", None),))
    errors = io.StringIO()
    commands = _commands(settings, _client(), errors)
    assert commands.dispatch("realise") == 0
    assert commands.dispatch("freeze") == 0
    tree = settings.dataset_dir / "public"
    manifest = json.loads((tree / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"] = [
        item for item in manifest["files"] if item["path"] != "episodes/plan.jsonl"
    ]
    (tree / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tree / "episodes" / "plan.jsonl").unlink()
    assert commands.dispatch("verify") == 0
    assert commands.dispatch("episodes") == 1
    assert "no episode plan" in errors.getvalue()
    assert not (settings.evidence_dir / "runs").exists()


def test_an_api_under_another_policy_fails_the_command_and_writes_no_run(
    tmp_path: Path,
) -> None:
    settings = OfflineSettings().build(tmp_path, True)
    _plan(settings, (_episode("e-open", "T2", "open", None),))
    client = _client()
    client.policy = "prototype-9"
    errors = io.StringIO()
    commands = _commands(settings, client, errors)
    assert commands.dispatch("realise") == 0
    assert commands.dispatch("freeze") == 0
    assert commands.dispatch("episodes") == 1
    assert "policy version prototype-9 != prototype-2" in errors.getvalue()
    assert not any((settings.evidence_dir / "runs").glob("*/summary.json"))


def test_a_plan_with_a_repeated_episode_id_fails_before_any_turn(
    tmp_path: Path,
) -> None:
    settings = OfflineSettings().build(tmp_path, True)
    repeated = _episode("e-open", "T2", "open", None)
    _plan(settings, (repeated, repeated))
    client = _client()
    errors = io.StringIO()
    commands = _commands(settings, client, errors)
    assert commands.dispatch("realise") == 0
    assert commands.dispatch("freeze") == 0
    assert commands.dispatch("episodes") == 1
    assert "appears twice" in errors.getvalue()
    assert client.prompts == []


def test_episodes_refuses_without_a_client_a_plan_or_a_known_role(
    tmp_path: Path,
) -> None:
    settings = OfflineSettings().build(tmp_path, True)
    _plan(settings, ())
    errors = io.StringIO()
    offline = _commands(settings, None, errors)
    assert offline.dispatch("episodes") == 1
    assert "needs a tutor client" in errors.getvalue()
    commands = _commands(settings, _client(), errors)
    assert commands.dispatch("episodes") == 1
    assert "no realised stimuli" in errors.getvalue()
    assert commands.dispatch("realise") == 0
    assert commands.dispatch("freeze") == 0
    assert commands.dispatch("episodes") == 1
    assert "has no episodes" in errors.getvalue()
    _plan(settings, (_episode("e-t1", "T1", "open", None),))
    assert commands.dispatch("realise") == 0
    (settings.dataset_dir / "public" / "manifest.json").unlink()
    assert commands.dispatch("freeze") == 0
    assert commands.dispatch("episodes") == 1
    assert "no tutor role T1" in errors.getvalue()
    assert not (settings.evidence_dir / "runs").exists() or not any(
        (settings.evidence_dir / "runs").glob("*/summary.json")
    )


def test_the_cli_wires_all_four_tutor_roles_and_accepts_episodes(
    tmp_path: Path,
) -> None:
    settings = OfflineSettings().build(tmp_path, True)
    errors = io.StringIO()
    cli = SimulationCli(SimulationCompositionRoot(settings), errors)
    assert cli.main(["episodes"]) == 1
    assert "episodes needs a tutor client" in errors.getvalue()
