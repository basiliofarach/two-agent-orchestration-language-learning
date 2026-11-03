"""The operator commands. ``build`` stays until a corpus fetch exists."""

from pathlib import Path
from typing import TextIO

from pydantic import ValidationError

from tutor_sim.application.freeze import (
    ByteDigest,
    FreezeJob,
    Freezer,
    FrozenVersion,
    ManifestFile,
    ManifestMismatch,
    ManifestVerifier,
    RejectedSource,
    StimulusFile,
    StimulusMismatch,
)
from tutor_sim.application.oracle import ReportAssembly, ReportBuilder
from tutor_sim.application.realise import (
    ActiveTreeFile,
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
from tutor_sim.domain.models.identity import SimulationNamespace
from tutor_sim.domain.models.manifest import RoleModelPin
from tutor_sim.domain.models.observation import CampaignLine, Observation
from tutor_sim.domain.models.report import CaseResult
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
            return 0 if self._verified() is not None else 1
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
        ActiveTreeFile().write(self._root(), tree)
        return 0

    def _freeze(self) -> int:
        try:
            plan = PlanFile().load(self._root() / "plan.json")
        except FileNotFoundError as exc:
            self._errors.write(f"tutor_sim: {exc}\n")
            return 1
        tree = self._resolve()
        if tree is None:
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
            role_model=RoleModelPin(
                name="echo" if self._settings.role_fixture else "ollama",
                weights_sha=self._model.weights_sha(),
            ),
            sources=self._sources,
            cases=cases,
            tree=tree,
        )
        manifest_path = self._root() / tree / "manifest.json"
        try:
            existing = (
                ManifestFile().load(manifest_path) if manifest_path.is_file() else None
            )
        except (OSError, ValidationError) as exc:
            self._errors.write(f"tutor_sim: {exc}\n")
            return 1
        try:
            Freezer(self._clock, self._store).freeze(job, files, existing)
        except (RejectedSource, StimulusMismatch, FrozenVersion) as exc:
            self._errors.write(f"tutor_sim: {exc}\n")
            return 1
        return 0

    def _verified(self) -> DatasetTree | None:
        """The active tree once its manifest verifies; none after an error."""
        tree = self._resolve()
        if tree is None:
            return None
        path = self._root() / tree / "manifest.json"
        if not path.is_file():
            self._errors.write("tutor_sim: no manifest\n")
            return None
        try:
            ManifestVerifier(self._root()).verify(ManifestFile().load(path))
        except (ManifestMismatch, FileNotFoundError, OSError) as exc:
            self._errors.write(f"tutor_sim: {exc}\n")
            return None
        return tree

    def _run(self) -> int:
        tutor = self._tutor
        if tutor is None:
            self._errors.write("tutor_sim: run needs a tutor client\n")
            return 1
        tree = self._verified()
        if tree is None:
            return 1
        runner = Tier1Runner(tutor, self._role)
        learners = SimulationNamespace()
        recorded: list[CampaignLine] = []
        try:
            for case in self._read(tree, "stimuli/test.jsonl"):
                record = runner.run(
                    case,
                    case.utterance,
                    learners.learner_id(case.persona_id),
                    "tutor-sim",
                )
                recorded.append(
                    CampaignLine(
                        case_id=record.case_id,
                        errored=record.errored,
                        observation=record.observation,
                    )
                )
        except (CampaignAbort, PolicyMismatch) as exc:
            self._errors.write(f"tutor_sim: {exc}\n")
            return 1
        rows = tuple(recorded)
        CampaignFile().write(self._settings.evidence_dir / "campaign.jsonl", rows)
        ObservationFile().write(
            self._settings.evidence_dir / "observations.jsonl",
            self._observations(rows),
        )
        return 0

    def _report(self) -> int:
        tree = self._verified()
        if tree is None:
            return 1
        try:
            lines = CampaignFile().read(self._settings.evidence_dir / "campaign.jsonl")
        except FileNotFoundError:
            self._errors.write("tutor_sim: no campaign results\n")
            return 1
        manifest = ManifestFile().load(self._root() / tree / "manifest.json")
        request = ReportAssembly().request(
            self._run_id(),
            manifest.dataset_version,
            "tier-1",
            self._read(tree, "stimuli/test.jsonl"),
            lines,
        )
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
        ResultFile().write(
            self._settings.evidence_dir / "results.jsonl",
            tuple(item.result for item in request.scored),
        )
        return 0

    def _run_id(self) -> str:
        return "run-" + self._clock.now().strftime("%Y%m%dT%H%M%S")

    def _observations(self, rows: tuple[CampaignLine, ...]) -> tuple[Observation, ...]:
        found: list[Observation] = []
        for row in rows:
            if row.observation is not None:
                found.append(row.observation)
        return tuple(found)

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

    def _resolve(self) -> DatasetTree | None:
        """The tree this realisation recorded. Two unmarked trees are refused."""
        root = self._root()
        recorded = ActiveTreeFile().read(root)
        if recorded is not None:
            if (root / recorded / "stimuli/test.jsonl").is_file():
                return recorded
            self._errors.write(
                "tutor_sim: the active stimulus tree has no test split\n"
            )
            return None
        candidates: tuple[DatasetTree, ...] = ("public", "restricted")
        present = tuple(
            tree
            for tree in candidates
            if (root / tree / "stimuli/test.jsonl").is_file()
        )
        if len(present) > 1:
            self._errors.write(
                "tutor_sim: both stimulus trees exist and none is active\n"
            )
            return None
        if len(present) == 1:
            return present[0]
        self._errors.write("tutor_sim: no realised stimuli\n")
        return None


class JsonlFile:
    """One JSON object per line. An empty sequence writes an empty file."""

    def _write(self, path: Path, lines: tuple[str, ...]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")

    def _read(self, path: Path) -> tuple[str, ...]:
        if not path.is_file():
            msg = "no campaign results"
            raise FileNotFoundError(msg)
        text = path.read_text(encoding="utf-8")
        return tuple(line for line in text.splitlines() if line)


class CampaignFile(JsonlFile):
    """Every case, including those that errored and have no observation."""

    def write(self, path: Path, rows: tuple[CampaignLine, ...]) -> None:
        """Replace the file with one line per case."""
        self._write(path, tuple(row.model_dump_json() for row in rows))

    def read(self, path: Path) -> tuple[CampaignLine, ...]:
        """The lines a report scores. A missing file is a command error."""
        return tuple(
            CampaignLine.model_validate_json(line) for line in self._read(path)
        )


class ObservationFile(JsonlFile):
    """Observations only. An errored case is absent here and present in the campaign."""

    def write(self, path: Path, rows: tuple[Observation, ...]) -> None:
        """Replace the file. Learner text is not on an observation."""
        self._write(path, tuple(row.model_dump_json() for row in rows))


class ResultFile(JsonlFile):
    """One comparison per frozen case, including the ones that errored."""

    def write(self, path: Path, rows: tuple[CaseResult, ...]) -> None:
        """Replace the results file the report just scored."""
        self._write(path, tuple(row.model_dump_json() for row in rows))
