"""Freeze a realised dataset and check the freeze later."""

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from tutor_sim.domain.models.case import StimulusCase
from tutor_sim.domain.models.manifest import (
    FileDigest,
    Manifest,
    RoleModelPin,
    SourceRef,
)
from tutor_sim.domain.models.source import SourceRecord
from tutor_sim.domain.models.storage import DatasetTree, DatasetWrite
from tutor_sim.domain.ports.clock import ClockPort
from tutor_sim.domain.ports.dataset_store import DatasetStorePort


class RejectedSource(ValueError):
    """A rejected licence review cannot be frozen."""


class RestrictedPublication(ValueError):
    """A non-redistributable source was aimed at ``public/``."""


class ManifestMismatch(ValueError):
    """A file or the test-split digest does not match the manifest."""


class StimulusMismatch(ValueError):
    """A realised case does not belong to this freeze."""


class FrozenVersion(ValueError):
    """This dataset version is already frozen with different bytes."""


class FreezeJob(BaseModel):
    """What one freeze writes. Review status is copied, not judged."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_version: str
    seed: int
    policy_version: str
    role_model: RoleModelPin
    sources: tuple[SourceRecord, ...]
    cases: tuple[StimulusCase, ...]
    tree: DatasetTree


class LicenceTermsGate:
    """Terms only. A pending review is recorded and does not block the freeze."""

    def admit(self, sources: tuple[SourceRecord, ...], tree: DatasetTree) -> None:
        """Refuse a rejected source, and a restricted source under ``public/``."""
        for source in sources:
            if source.licence_review == "rejected":
                msg = f"{source.source_id} is rejected"
                raise RejectedSource(msg)
            if tree == "public" and not source.redistributable:
                msg = f"{source.source_id} is not redistributable"
                raise RestrictedPublication(msg)


class CaseKey:
    """Sort stimuli by case id for the test-split digest."""

    def case_id(self, case: StimulusCase) -> str:
        """The sort key."""
        return case.case_id


class TestSplitDigest:
    """SHA-256 of the test split as canonical JSON, sorted by case id."""

    def of(self, cases: tuple[StimulusCase, ...]) -> str:
        """The digest a later verify recomputes."""
        test = tuple(case for case in cases if case.split == "test")
        ordered = tuple(sorted(test, key=self._key))
        payload = [case.model_dump(mode="json") for case in ordered]
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    def _key(self, case: StimulusCase) -> str:
        return CaseKey().case_id(case)


class ByteDigest:
    """SHA-256 of a file the manifest names."""

    def of_file(self, path: Path, relative: str, tree: DatasetTree) -> FileDigest:
        """Hash the bytes on disk."""
        body = path.read_bytes()
        return FileDigest(
            path=relative,
            tree=tree,
            sha256=hashlib.sha256(body).hexdigest(),
            bytes=len(body),
        )


class SourceSnapshot:
    """Copy review fields onto the manifest. Later confirmation does not move them."""

    def refs(self, sources: tuple[SourceRecord, ...]) -> tuple[SourceRef, ...]:
        """One ref per source, including a pending review."""
        return tuple(
            SourceRef(
                source_id=source.source_id,
                revision=source.revision,
                sha256=source.sha256,
                licence=source.licence,
                licence_review=source.licence_review,
            )
            for source in sources
        )


class StimulusFile:
    """Read the JSONL a freeze or a verify is checking."""

    def read(self, path: Path) -> tuple[StimulusCase, ...]:
        """Parse every non-blank line. A missing file is an empty split."""
        if not path.is_file():
            return ()
        rows: list[StimulusCase] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line:
                rows.append(StimulusCase.model_validate_json(line))
        return tuple(rows)


class ManifestWriter:
    """Build the manifest from the job, the clock, and the files just written."""

    def __init__(self, clock: ClockPort) -> None:
        self._clock = clock
        self._digest = TestSplitDigest()
        self._sources = SourceSnapshot()

    def build(self, job: FreezeJob, files: tuple[FileDigest, ...]) -> Manifest:
        """``frozen_at`` comes from the injected clock."""
        return Manifest(
            dataset_version=job.dataset_version,
            seed=job.seed,
            policy_version=job.policy_version,
            role_model=job.role_model,
            sources=self._sources.refs(job.sources),
            files=files,
            test_split_sha256=self._digest.of(job.cases),
            frozen_at=self._clock.now(),
        )


class StimulusAgreement:
    """The cases on disk must be the ones this freeze claims to fix."""

    def require(self, job: FreezeJob) -> None:
        """Refuse a case stamped for another version or another role model."""
        pin = job.role_model.weights_sha
        for case in job.cases:
            if (
                case.dataset_version != job.dataset_version
                or case.policy_version != job.policy_version
                or case.generator.weights_sha != pin
            ):
                msg = "realised cases do not match the freeze metadata"
                raise StimulusMismatch(msg)


class FreezeIdentity:
    """Two freezes of one version. The clock is not part of the identity."""

    def same(self, existing: Manifest, proposed: Manifest) -> bool:
        """True when only ``frozen_at`` could differ."""
        kept = {"frozen_at"}
        return existing.model_dump(exclude=kept) == proposed.model_dump(exclude=kept)


class Freezer:
    """Admit the sources, then write the manifest through the dataset store."""

    def __init__(self, clock: ClockPort, store: DatasetStorePort) -> None:
        self._clock = clock
        self._store = store
        self._gate = LicenceTermsGate()
        self._writer = ManifestWriter(clock)
        self._cases = StimulusAgreement()
        self._identity = FreezeIdentity()

    def freeze(
        self,
        job: FreezeJob,
        files: tuple[FileDigest, ...],
        existing: Manifest | None = None,
    ) -> Manifest:
        """Pending is allowed. A frozen version is not rewritten."""
        self._gate.admit(job.sources, job.tree)
        self._cases.require(job)
        manifest = self._writer.build(job, files)
        if existing is not None:
            if not self._identity.same(existing, manifest):
                msg = "this dataset version is already frozen"
                raise FrozenVersion(msg)
            return existing
        self._store.write(
            DatasetWrite(
                relative_path="manifest.json",
                body=manifest.model_dump_json().encode("utf-8"),
                redistributable=job.tree == "public",
                tree=job.tree,
            )
        )
        return manifest


class ManifestVerifier:
    """Recompute every file digest and the test-split digest."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._files = ByteDigest()
        self._split = TestSplitDigest()
        self._stimuli = StimulusFile()

    def verify(self, manifest: Manifest) -> None:
        """Raise when a byte or the test split moved after the freeze."""
        for item in manifest.files:
            path = self._root / item.tree / item.path
            digest = self._files.of_file(path, item.path, item.tree)
            if digest.sha256 != item.sha256 or digest.bytes != item.bytes:
                msg = f"{item.path} does not match the manifest"
                raise ManifestMismatch(msg)
        test = self._stimuli.read(
            self._root / self._tree(manifest) / "stimuli/test.jsonl"
        )
        if self._split.of(test) != manifest.test_split_sha256:
            msg = "the test split does not match the manifest"
            raise ManifestMismatch(msg)

    def _tree(self, manifest: Manifest) -> DatasetTree:
        for item in manifest.files:
            if item.path == "stimuli/test.jsonl":
                return item.tree
        msg = "the manifest has no test split"
        raise ManifestMismatch(msg)


class ManifestFile:
    """Read ``manifest.json`` back."""

    def load(self, path: Path) -> Manifest:
        """A missing manifest is a command error."""
        if not path.is_file():
            msg = "no manifest"
            raise FileNotFoundError(msg)
        return Manifest.model_validate_json(path.read_text(encoding="utf-8"))
