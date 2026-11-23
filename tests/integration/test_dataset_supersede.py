"""Freezing a new dataset version through the operator command.

The real command, dataset store and manifest files are wired; only the
role model is the echo fixture. The first freeze is the baseline. A plan
with a new version freezes over it and keeps the baseline's manifest in
``superseded/``. The run that used the baseline can still be matched to
those checksums.
"""

import io
import json
from datetime import UTC, datetime
from pathlib import Path

from tests.support.persona_files import PersonaFiles
from tests.unit.sim.test_kernel import OfflineSettings, PinnedSource
from tests.unit.sim.test_simulation_campaign import _case

from tutor_sim.adapters.file_dataset_store import FileDatasetStore
from tutor_sim.adapters.frozen_clock import FrozenClock
from tutor_sim.adapters.role_model import EchoRoleModel
from tutor_sim.application.commands import CampaignCommands
from tutor_sim.application.realise import RealisePlan
from tutor_sim.application.roles import AbsentTutor, TutorRoster
from tutor_sim.domain.models.manifest import Manifest
from tutor_sim.settings import SimulationSettings

_BASELINE = "sim-dataset/unreleased"
_NEXT = "sim-dataset/unreleased-2"


def _plan(settings: SimulationSettings, version: str) -> None:
    case = _case().model_copy(update={"dataset_version": version})
    plan = RealisePlan(
        dataset_version=version, policy_version="prototype-2", seed=1, cases=(case,)
    )
    settings.dataset_dir.mkdir(parents=True, exist_ok=True)
    (settings.dataset_dir / "plan.json").write_text(
        plan.model_dump_json(), encoding="utf-8"
    )
    PersonaFiles().write(settings.dataset_dir)


def _commands(settings: SimulationSettings, errors: io.StringIO) -> CampaignCommands:
    return CampaignCommands(
        settings,
        FrozenClock(datetime(2026, 11, 20, tzinfo=UTC)),
        FileDatasetStore(settings.dataset_dir),
        EchoRoleModel(),
        (PinnedSource().record(),),
        None,
        AbsentTutor(),
        TutorRoster(()),
        errors,
    )


def _frozen(settings: SimulationSettings, version: str) -> int:
    _plan(settings, version)
    errors = io.StringIO()
    commands = _commands(settings, errors)
    assert commands.dispatch("pupil-messages") == 0, errors.getvalue()
    return commands.dispatch("freeze")


def _manifest(path: Path) -> Manifest:
    return Manifest.model_validate_json(path.read_text(encoding="utf-8"))


def test_a_new_version_freezes_and_keeps_the_baseline_manifest(
    tmp_path: Path,
) -> None:
    settings = OfflineSettings().build(tmp_path, True)
    assert _frozen(settings, _BASELINE) == 0
    tree = settings.dataset_dir / "public"
    baseline = (tree / "manifest.json").read_bytes()
    assert _frozen(settings, _NEXT) == 0
    assert _manifest(tree / "manifest.json").dataset_version == _NEXT
    kept = tree / "superseded" / "sim-dataset_unreleased" / "manifest.json"
    assert kept.read_bytes() == baseline
    assert _commands(settings, io.StringIO()).dispatch("verify") == 0


def test_freezing_the_new_version_twice_changes_nothing(tmp_path: Path) -> None:
    settings = OfflineSettings().build(tmp_path, True)
    assert _frozen(settings, _BASELINE) == 0
    assert _frozen(settings, _NEXT) == 0
    tree = settings.dataset_dir / "public"
    before = sorted(path.name for path in (tree / "superseded").iterdir())
    current = (tree / "manifest.json").read_bytes()
    assert _commands(settings, io.StringIO()).dispatch("freeze") == 0
    assert (tree / "manifest.json").read_bytes() == current
    assert sorted(path.name for path in (tree / "superseded").iterdir()) == before


def test_a_superseded_version_with_other_bytes_is_refused(tmp_path: Path) -> None:
    settings = OfflineSettings().build(tmp_path, True)
    assert _frozen(settings, _BASELINE) == 0
    assert _frozen(settings, _NEXT) == 0
    kept = (
        settings.dataset_dir / "public" / "superseded" / "sim-dataset_unreleased"
    ) / "manifest.json"
    moved = json.loads(kept.read_text(encoding="utf-8"))
    moved["test_split_sha256"] = "ab" * 32
    kept.write_text(json.dumps(moved), encoding="utf-8")
    errors = io.StringIO()
    _plan(settings, _BASELINE)
    commands = _commands(settings, errors)
    assert commands.dispatch("pupil-messages") == 0
    assert commands.dispatch("freeze") == 1
    assert "already frozen (superseded)" in errors.getvalue()


def test_an_unreadable_kept_manifest_fails_the_freeze(tmp_path: Path) -> None:
    settings = OfflineSettings().build(tmp_path, True)
    assert _frozen(settings, _BASELINE) == 0
    broken = settings.dataset_dir / "public" / "superseded" / "x" / "manifest.json"
    broken.parent.mkdir(parents=True)
    broken.write_text("{", encoding="utf-8")
    errors = io.StringIO()
    assert _commands(settings, errors).dispatch("freeze") == 1
    assert errors.getvalue().startswith("tutor_sim:")
