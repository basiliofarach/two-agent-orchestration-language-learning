"""``measures`` on a finished run, through the operator command (SIMULATION §9.5).

The real command, dataset store, manifest, freeze, persona cards, oracle,
run directory and measure classes are wired. The tutor API and the role
model are stubbed, and the tagger is the word-list fixture: TreeTagger's
own output is covered by its adapter tests, not here.
"""

import io
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from tests.integration.test_episode_resume import _EPISODES, _RUN, _ready, _retained
from tests.support.cefrj_measures import CefrjFetch, CefrjSources
from tests.support.grammar_workbook import WordTagger
from tests.support.persona_files import PersonaFiles
from tests.unit.sim.test_episode_runner import RecordingTutor
from tests.unit.sim.test_kernel import OfflineSettings, PinnedSource
from tests.unit.sim.test_measures import ReadsRecord
from tests.unit.sim.test_simulation_campaign import _observation

from tutor_sim.adapters.file_dataset_store import FileDatasetStore
from tutor_sim.adapters.frozen_clock import FrozenClock
from tutor_sim.adapters.role_model import EchoRoleModel
from tutor_sim.application.commands import CampaignCommands
from tutor_sim.application.measures import MeasureSources
from tutor_sim.application.realise import RealisePlan
from tutor_sim.application.roles import (
    AbsentTutor,
    ComplacentTutor,
    StoppingTutor,
    TutorRoster,
)
from tutor_sim.cli import SimulationCli
from tutor_sim.composition import SimulationCompositionRoot
from tutor_sim.domain.models.case import CaseSpec, Expected
from tutor_sim.domain.models.measures import MeasuredText, RunMeasures
from tutor_sim.domain.models.observation import CampaignLine
from tutor_sim.domain.models.report import SimulationReport
from tutor_sim.domain.ports.tutor_client import TutorClientPort
from tutor_sim.settings import SimulationSettings

_WHEN = datetime(2026, 11, 4, 12, tzinfo=UTC)
_TIER1 = "run-20261104T130000"
_EXERCISE = UUID(int=1)
_EXPLANATION = UUID(int=2)


def _commands(
    settings: SimulationSettings,
    client: TutorClientPort | None,
    errors: io.StringIO,
    measures: MeasureSources | None = None,
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
        None,
        None,
        measures,
    )


def _sources() -> MeasureSources:
    return MeasureSources(CefrjFetch(), CefrjSources().records(), WordTagger())


def _measure(
    settings: SimulationSettings, run_id: str, client: TutorClientPort | None
) -> tuple[int, str]:
    errors = io.StringIO()
    commands = _commands(
        settings.model_copy(update={"run_id": run_id}), client, errors, _sources()
    )
    return commands.dispatch("measures"), errors.getvalue()


def _read(run: Path) -> tuple[RunMeasures, tuple[MeasuredText, ...]]:
    record = RunMeasures.model_validate_json(
        (run / "measures.json").read_text(encoding="utf-8")
    )
    lines = tuple(
        MeasuredText.model_validate_json(line)
        for line in (run / "measures.jsonl").read_text(encoding="utf-8").splitlines()
    )
    return record, lines


def _case(case_id: str, intent: str, topic: str | None) -> CaseSpec:
    return CaseSpec(
        case_id=case_id,
        dataset_version="sim-dataset/0.1.0",
        policy_version="prototype-2",
        split="test",
        persona_id="p-a2-es-12_14-01",
        intent=intent,  # type: ignore[arg-type]
        variant="canonical",
        topic_id=topic,
        expected=Expected(accept=("released_for_approval",), basis="requirement"),
    )


def _tier1_ready(tmp_path: Path) -> SimulationSettings:
    """Freeze one I2 case on Profile item 13 and one I1 case, then score a run."""
    settings = OfflineSettings().build(tmp_path, True)
    plan = RealisePlan(
        dataset_version="sim-dataset/0.1.0",
        policy_version="prototype-2",
        seed=1,
        cases=(_case("c-ex", "I2", "gp-13"), _case("c-gr", "I1", None)),
    )
    settings.dataset_dir.mkdir(parents=True, exist_ok=True)
    (settings.dataset_dir / "plan.json").write_text(
        plan.model_dump_json(), encoding="utf-8"
    )
    PersonaFiles().write(settings.dataset_dir)
    commands = _commands(settings, None, io.StringIO())
    assert commands.dispatch("pupil-messages") == 0
    assert commands.dispatch("freeze") == 0
    run = settings.evidence_dir / "runs" / _TIER1
    run.mkdir(parents=True)
    lines = (
        CampaignLine(
            case_id="c-ex",
            errored=False,
            observation=_observation(case_id="c-ex", turn_id=_EXERCISE),
        ),
        CampaignLine(
            case_id="c-gr",
            errored=False,
            observation=_observation(case_id="c-gr", turn_id=_EXPLANATION),
        ),
    )
    (run / "campaign.jsonl").write_text(
        "".join(line.model_dump_json() + "\n" for line in lines), encoding="utf-8"
    )
    (run / "observations.jsonl").write_text("", encoding="utf-8")
    scored = settings.model_copy(update={"run_id": _TIER1})
    assert _commands(scored, None, io.StringIO()).dispatch("report") == 0
    return settings


def _evidence(run: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(run.glob("*.json*"))}


def test_a_tier_1_run_is_measured_from_the_replies_the_api_returns(
    tmp_path: Path,
) -> None:
    settings = _tier1_ready(tmp_path)
    run = settings.evidence_dir / "runs" / _TIER1
    before = _evidence(run)
    client = ReadsRecord({_EXERCISE: "Give me a cat", _EXPLANATION: "I wish"})
    code, errors = _measure(settings, _TIER1, client)
    assert code == 0, errors
    record, lines = _read(run)
    assert record.tier == "1"
    assert record.dataset_version == "sim-dataset/0.1.0"
    assert record.tagger_revision == "word-tagger-fixture"
    assert (record.wordlist_revision, record.profile_revision) == ("1.6", "2025-02-25")
    assert [(row.level, row.k, row.n) for row in record.target_structure] == [
        ("A2", 1, 1),
        (None, 1, 1),
    ]
    overall = record.level_fit[-1]
    assert (overall.level, overall.n, overall.at_95) == (None, 2, 1)
    assert sorted(client.reads) == [_EXERCISE, _EXPLANATION]
    replies = {line.text_id: line for line in lines if line.kind == "reply"}
    assert replies["c-ex"].target_present is True
    assert replies["c-gr"].coverage == 0.5
    body = (run / "measures.jsonl").read_text(encoding="utf-8")
    assert "Give me a cat" not in body
    assert "wish" not in body
    after = _evidence(run)
    assert {name: after[name] for name in before} == before


def test_a_reply_the_api_no_longer_holds_is_counted_unreadable(
    tmp_path: Path,
) -> None:
    settings = _tier1_ready(tmp_path)
    code, errors = _measure(settings, _TIER1, ReadsRecord({_EXERCISE: "a cat"}))
    assert code == 0, errors
    record, _ = _read(settings.evidence_dir / "runs" / _TIER1)
    assert record.unreadable == 1
    assert record.level_fit[-1].n == 1


def test_a_run_is_measured_once(tmp_path: Path) -> None:
    settings = _tier1_ready(tmp_path)
    client = ReadsRecord({_EXERCISE: "a cat"})
    assert _measure(settings, _TIER1, client)[0] == 0
    run = settings.evidence_dir / "runs" / _TIER1
    kept = (run / "measures.json").read_bytes()
    code, errors = _measure(settings, _TIER1, client)
    assert code == 1
    assert "is already measured" in errors
    assert (run / "measures.json").read_bytes() == kept


def test_a_tier_1_run_scored_against_another_dataset_is_refused(
    tmp_path: Path,
) -> None:
    settings = _tier1_ready(tmp_path)
    run = settings.evidence_dir / "runs" / _TIER1
    report = SimulationReport.model_validate_json(
        (run / "report.json").read_text(encoding="utf-8")
    )
    (run / "report.json").write_text(
        report.model_copy(
            update={"dataset_version": "sim-dataset/older"}
        ).model_dump_json(),
        encoding="utf-8",
    )
    client = ReadsRecord({_EXERCISE: "a cat"})
    code, errors = _measure(settings, _TIER1, client)
    assert code == 1
    assert "scored against sim-dataset/older" in errors
    assert client.reads == []
    assert not (run / "measures.json").exists()


def test_a_tier_1_run_needs_the_api(tmp_path: Path) -> None:
    settings = _tier1_ready(tmp_path)
    code, errors = _measure(settings, _TIER1, None)
    assert code == 1
    assert "needs a tutor client" in errors


def test_a_run_without_a_report_or_without_an_id_is_refused(tmp_path: Path) -> None:
    settings = _tier1_ready(tmp_path)
    (settings.evidence_dir / "runs" / "run-20261104T140000").mkdir()
    code, errors = _measure(settings, "run-20261104T140000", None)
    assert code == 1
    assert "has no report yet" in errors
    unnamed = io.StringIO()
    assert _commands(settings, None, unnamed, _sources()).dispatch("measures") == 1
    assert "needs SIM_RUN_ID" in unnamed.getvalue()
    unwired = io.StringIO()
    assert _commands(settings, None, unwired).dispatch("measures") == 1
    assert "needs the CEFR-J sources" in unwired.getvalue()


def test_a_tier_2_run_is_measured_from_its_own_transcripts(tmp_path: Path) -> None:
    settings = _ready(tmp_path)
    episodes = _commands(settings, _retained(RecordingTutor()), io.StringIO())
    assert episodes.dispatch("episodes") == 0
    run = settings.evidence_dir / "runs" / _RUN
    before = _evidence(run)
    code, errors = _measure(settings, _RUN, None)
    assert code == 0, errors
    record, lines = _read(run)
    assert record.tier == "2"
    assert record.target_structure == ()
    assert record.unreadable == 0
    turns = 3 * len(_EPISODES)
    assert sum(line.kind == "pupil" for line in lines) == turns
    assert sum(line.kind == "reply" for line in lines) == turns
    # ``release-<n>`` lists no CEFR-J word, so every reply is unscored.
    assert (record.level_fit[-1].n, record.level_fit[-1].unscored) == (0, turns)
    assert all(row.level in {"A2", None} for row in record.pupil_level)
    assert "release-0" not in (run / "measures.jsonl").read_text(encoding="utf-8")
    after = _evidence(run)
    assert {name: after[name] for name in before} == before


def test_a_tier_2_trail_naming_an_episode_outside_the_plan_is_refused(
    tmp_path: Path,
) -> None:
    settings = _ready(tmp_path)
    episodes = _commands(settings, _retained(RecordingTutor()), io.StringIO())
    assert episodes.dispatch("episodes") == 0
    run = settings.evidence_dir / "runs" / _RUN
    with (run / "episodes.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"episode_id": "e-elsewhere", "facts": []}) + "\n")
    code, errors = _measure(settings, _RUN, None)
    assert code == 1
    assert "e-elsewhere is not in the frozen episode plan" in errors


def test_the_composition_root_wires_the_measures(tmp_path: Path) -> None:
    root = SimulationCompositionRoot(OfflineSettings().build(tmp_path, True))
    errors = io.StringIO()
    assert SimulationCli(root, errors).main(["measures"]) == 1
    assert "needs SIM_RUN_ID" in errors.getvalue()
    assert "needs the CEFR-J sources" not in errors.getvalue()
