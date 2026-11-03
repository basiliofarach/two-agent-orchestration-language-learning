"""The operator commands. ``build`` stays until a corpus fetch exists."""

from pathlib import Path
from typing import TextIO
from uuid import UUID

from tutor_sim.application.freeze import (
    ByteDigest,
    FreezeJob,
    Freezer,
    ManifestFile,
    ManifestMismatch,
    ManifestVerifier,
    RejectedSource,
    StimulusFile,
)
from tutor_sim.application.oracle import ReportBuilder, ReportRequest
from tutor_sim.application.realise import (
    ConstructionCheck,
    DatasetBytes,
    DiscardLog,
    NoiseTransformer,
    PayloadIndex,
    PlanFile,
    PupilRealiser,
    ReleaseTree,
    StimulusLines,
)
from tutor_sim.application.tier1 import CampaignAbort, PolicyMismatch, Tier1Runner
from tutor_sim.domain.models.case import StimulusCase
from tutor_sim.domain.models.manifest import RoleModelPin
from tutor_sim.domain.models.source import SourceRecord
from tutor_sim.domain.models.storage import DatasetTree
from tutor_sim.domain.ports.clock import ClockPort
from tutor_sim.domain.ports.dataset_store import DatasetStorePort
from tutor_sim.domain.ports.role_model import RoleModelPort
from tutor_sim.domain.ports.tutor_client import TutorClientPort
from tutor_sim.domain.ports.tutor_role import TutorRolePort
from tutor_sim.settings import SimulationSettings


class CampaignCommands:
    """realise, freeze, verify, run and report. ``build`` is still refused."""

    def __init__(
        self,
        settings: SimulationSettings,
        clock: ClockPort,
        store: DatasetStorePort,
        model: RoleModelPort,
        sources: tuple[SourceRecord, ...],
        tutor: TutorClientPort | None,
        role: TutorRolePort,
        errors: TextIO,
    ) -> None:
        self._settings = settings
        self._clock = clock
        self._store = store
        self._model = model
        self._sources = sources
        self._tutor = tutor
        self._role = role
        self._errors = errors

    def dispatch(self, command: str) -> int:
        """Run one command. An unknown name is a usage error."""
        if command == "build":
            self._errors.write("tutor_sim: build is not implemented yet\n")
            return 1
        if command == "realise":
            return self._realise()
        if command == "freeze":
            return self._freeze()
        if command == "verify":
            return self._verify()
        if command == "run":
            return self._run()
        if command == "report":
            return self._report()
        self._errors.write(f"tutor_sim: {command} is not a command\n")
        return 2

    def _realise(self) -> int:
        try:
            plan = PlanFile().load(self._root() / "plan.json")
        except FileNotFoundError as exc:
            self._errors.write(f"tutor_sim: {exc}\n")
            return 1
        index = PayloadIndex(plan.payloads)
        realiser = PupilRealiser(self._model, ConstructionCheck(), NoiseTransformer())
        realised: list[StimulusCase] = []
        try:
            for offset, case in enumerate(plan.cases):
                realised.append(
                    realiser.realise(
                        case, index.text(case.payload_id), plan.seed + offset
                    )
                )
        except KeyError as exc:
            self._errors.write(f"tutor_sim: {exc}\n")
            return 1
        cases = tuple(realised)
        tree = ReleaseTree().choose(self._flags(index))
        writer = DatasetBytes(self._store)
        lines = StimulusLines()
        writer.write("stimuli/test.jsonl", lines.body(self._split(cases, "test")), tree)
        writer.write("stimuli/dev.jsonl", lines.body(self._split(cases, "dev")), tree)
        writer.write("discards.json", DiscardLog().body(cases), tree)
        return 0

    def _freeze(self) -> int:
        try:
            plan = PlanFile().load(self._root() / "plan.json")
        except FileNotFoundError as exc:
            self._errors.write(f"tutor_sim: {exc}\n")
            return 1
        tree = self._placed()
        if tree is None:
            self._errors.write("tutor_sim: no realised stimuli\n")
            return 1
        cases = self._read(tree, "stimuli/test.jsonl") + self._read(
            tree, "stimuli/dev.jsonl"
        )
        files = tuple(
            ByteDigest().of_file(self._root() / tree / relative, relative, tree)
            for relative in ("stimuli/test.jsonl", "stimuli/dev.jsonl", "discards.json")
        )
        job = FreezeJob(
            dataset_version=plan.dataset_version,
            seed=plan.seed,
            policy_version=plan.policy_version,
            role_model=RoleModelPin(name="echo", weights_sha=self._model.weights_sha()),
            sources=self._sources,
            cases=cases,
            tree=tree,
        )
        try:
            Freezer(self._clock, self._store).freeze(job, files)
        except RejectedSource as exc:
            self._errors.write(f"tutor_sim: {exc}\n")
            return 1
        return 0

    def _verify(self) -> int:
        path = self._manifest()
        if path is None:
            self._errors.write("tutor_sim: no manifest\n")
            return 1
        try:
            ManifestVerifier(self._root()).verify(ManifestFile().load(path))
        except (ManifestMismatch, FileNotFoundError, OSError) as exc:
            self._errors.write(f"tutor_sim: {exc}\n")
            return 1
        return 0

    def _run(self) -> int:
        tutor = self._tutor
        if tutor is None:
            self._errors.write("tutor_sim: run needs a tutor client\n")
            return 1
        tree = self._placed()
        if tree is None:
            self._errors.write("tutor_sim: no realised stimuli\n")
            return 1
        runner = Tier1Runner(tutor, self._role)
        lines: list[str] = []
        try:
            for case in self._read(tree, "stimuli/test.jsonl"):
                record = runner.run(case, case.utterance, UUID(int=1), "tutor-sim")
                if record.observation is not None:
                    lines.append(record.observation.model_dump_json())
        except (CampaignAbort, PolicyMismatch) as exc:
            self._errors.write(f"tutor_sim: {exc}\n")
            return 1
        destination = self._settings.evidence_dir / "observations.jsonl"
        destination.parent.mkdir(parents=True, exist_ok=True)
        text = "\n".join(lines) + ("\n" if lines else "")
        destination.write_text(text, encoding="utf-8")
        return 0

    def _report(self) -> int:
        path = self._root() / "report-input.json"
        if not path.is_file():
            self._errors.write("tutor_sim: no report input\n")
            return 1
        request = ReportRequest.model_validate_json(path.read_text(encoding="utf-8"))
        report = ReportBuilder().build(
            request.run_id,
            request.dataset_version,
            request.label,
            self._sources,
            request.used_source_ids,
            request.scored,
            request.facts,
        )
        destination = self._settings.evidence_dir / "report.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        return 0

    def _root(self) -> Path:
        return self._settings.dataset_dir

    def _flags(self, index: PayloadIndex) -> tuple[bool, ...]:
        source_flags = tuple(source.redistributable for source in self._sources)
        payload_flags = tuple(item.redistributable for item in index.items())
        return source_flags + payload_flags

    def _split(
        self, cases: tuple[StimulusCase, ...], split: str
    ) -> tuple[StimulusCase, ...]:
        return tuple(case for case in cases if case.split == split)

    def _read(self, tree: DatasetTree, relative: str) -> tuple[StimulusCase, ...]:
        return StimulusFile().read(self._root() / tree / relative)

    def _placed(self) -> DatasetTree | None:
        for tree in ("public", "restricted"):
            if (self._root() / tree / "stimuli/test.jsonl").is_file():
                return tree
        return None

    def _manifest(self) -> Path | None:
        for tree in ("public", "restricted"):
            path = self._root() / tree / "manifest.json"
            if path.is_file():
                return path
        return None
