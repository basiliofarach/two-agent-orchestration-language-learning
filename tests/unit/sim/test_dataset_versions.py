"""A new dataset version supersedes the frozen one; no version is rewritten.

The CEFR-SP baseline was frozen as ``sim-dataset/unreleased``. The CEFR-J
build is a different dataset, so it is a different version. Freezing it
moves the baseline's manifest to ``superseded/<version>/manifest.json``
instead of overwriting it, so the checksums a finished run was scored
against stay on disk. Re-freezing any version already frozen, current or
superseded, with different bytes is still refused.
"""

import pytest
from tests.unit.sim.test_kernel import PinnedSource
from tests.unit.sim.test_simulation_campaign import (
    _WHEN,
    CountingStore,
    _case,
    _pupil,
)

from tutor_sim.adapters.frozen_clock import FrozenClock
from tutor_sim.adapters.role_model import EchoRoleModel
from tutor_sim.application.cases import DATASET_VERSION
from tutor_sim.application.freeze import (
    FreezeJob,
    Freezer,
    FrozenVersion,
    SupersededPath,
)
from tutor_sim.application.realise import (
    ConstructionCheck,
    NoiseTransformer,
    PupilRealiser,
)
from tutor_sim.domain.models.manifest import Manifest, RoleModelPin


def _job(version: str) -> FreezeJob:
    model = EchoRoleModel()
    realised = PupilRealiser(
        model, ConstructionCheck(), NoiseTransformer(), _pupil()
    ).realise(_case(), None, 1)
    realised = realised.model_copy(update={"dataset_version": version})
    return FreezeJob(
        dataset_version=version,
        seed=1,
        policy_version=realised.policy_version,
        role_model=RoleModelPin(name="echo", weights_sha=model.weights_sha()),
        sources=(PinnedSource().record(),),
        cases=(realised,),
        tree="restricted",
    )


class RecordingStore(CountingStore):
    """Keeps the path of every write, in order."""

    def __init__(self) -> None:
        super().__init__()
        self.paths: list[str] = []

    def write(self, item) -> None:  # type: ignore[no-untyped-def]
        self.paths.append(item.relative_path)
        super().write(item)


def _frozen(version: str) -> Manifest:
    return Freezer(FrozenClock(_WHEN), CountingStore()).freeze(_job(version), ())


class TestDatasetVersion:
    def test_the_cefr_j_build_is_not_the_baseline_version(self) -> None:
        assert DATASET_VERSION != "sim-dataset/unreleased"
        assert DATASET_VERSION == "sim-dataset/unreleased-2"


class TestSupersededPath:
    def test_a_version_becomes_one_directory_name(self) -> None:
        assert (
            SupersededPath().of("sim-dataset/unreleased")
            == "superseded/sim-dataset_unreleased/manifest.json"
        )

    def test_nothing_in_a_version_escapes_the_superseded_directory(self) -> None:
        path = SupersededPath().of("../../etc/x")
        assert path.startswith("superseded/")
        assert path.count("/") == 2
        assert ".." not in path.split("/")[1]


class TestSupersede:
    def test_a_new_version_archives_the_frozen_manifest_then_writes_its_own(
        self,
    ) -> None:
        baseline = _frozen("sim-dataset/unreleased")
        store = RecordingStore()
        manifest = Freezer(FrozenClock(_WHEN), store).freeze(
            _job("sim-dataset/unreleased-2"), (), baseline
        )
        assert manifest.dataset_version == "sim-dataset/unreleased-2"
        assert store.paths == [
            "superseded/sim-dataset_unreleased/manifest.json",
            "manifest.json",
        ]

    def test_the_archive_is_the_frozen_manifest_byte_for_byte(self) -> None:
        baseline = _frozen("sim-dataset/unreleased")
        bodies: list[bytes] = []

        class Bodies(CountingStore):
            def write(self, item) -> None:  # type: ignore[no-untyped-def]
                bodies.append(item.body)

        Freezer(FrozenClock(_WHEN), Bodies()).freeze(
            _job("sim-dataset/unreleased-2"), (), baseline
        )
        assert Manifest.model_validate_json(bodies[0]) == baseline

    def test_an_identical_archive_is_not_written_again(self) -> None:
        baseline = _frozen("sim-dataset/unreleased")
        store = RecordingStore()
        Freezer(FrozenClock(_WHEN), store).freeze(
            _job("sim-dataset/unreleased-2"), (), baseline, (baseline,)
        )
        assert store.paths == ["manifest.json"]

    def test_a_different_archive_of_the_same_version_is_refused(self) -> None:
        baseline = _frozen("sim-dataset/unreleased")
        other = baseline.model_copy(update={"test_split_sha256": "ab" * 32})
        store = RecordingStore()
        with pytest.raises(FrozenVersion, match="sim-dataset/unreleased"):
            Freezer(FrozenClock(_WHEN), store).freeze(
                _job("sim-dataset/unreleased-2"), (), baseline, (other,)
            )
        assert store.paths == []

    def test_a_superseded_version_is_not_frozen_again_with_other_bytes(
        self,
    ) -> None:
        baseline = _frozen("sim-dataset/unreleased")
        second = _frozen("sim-dataset/unreleased-2")
        moved = baseline.model_copy(update={"test_split_sha256": "ab" * 32})
        store = RecordingStore()
        with pytest.raises(FrozenVersion, match="already frozen"):
            Freezer(FrozenClock(_WHEN), store).freeze(
                _job("sim-dataset/unreleased"), (), second, (moved,)
            )
        assert store.paths == []

    def test_the_same_version_with_other_bytes_is_still_refused(self) -> None:
        current = _frozen("sim-dataset/unreleased-2")
        changed = current.model_copy(update={"test_split_sha256": "ab" * 32})
        with pytest.raises(FrozenVersion, match="already frozen"):
            Freezer(FrozenClock(_WHEN), RecordingStore()).freeze(
                _job("sim-dataset/unreleased-2"), (), changed
            )
