"""The operator commands: build, realise, freeze, verify, run, episodes, report."""

from pathlib import Path
from typing import TextIO

from pydantic import ValidationError

from tutor_sim.application.build import DatasetBuild
from tutor_sim.application.episode import (
    DuplicateEpisode,
    EpisodePlanFile,
    EpisodeRunner,
    TranscriptFile,
)
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
from tutor_sim.application.oracle import (
    InvariantFacts,
    ReportAssembly,
    ReportBuilder,
)
from tutor_sim.application.progress import CommandProgress
from tutor_sim.application.realise import (
    ActiveTreeFile,
    ConstructionCheck,
    DatasetBytes,
    DiscardLog,
    NoiseTransformer,
    PayloadIndex,
    PersonaCardFile,
    PlanFile,
    PupilPrompt,
    PupilRealiser,
    ReleaseTree,
    StimulusLines,
    UnknownPersona,
)
from tutor_sim.application.roles import TutorRoster, UnknownTutorRole
from tutor_sim.application.run_files import RunDirectory
from tutor_sim.application.tier1 import (
    CampaignAbort,
    ModeGuard,
    PolicyMismatch,
    Tier1Runner,
)
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
    """build, realise, freeze, verify, run, episodes and report.

    ``build`` reads the pinned sources and writes the dataset and
    ``plan.json``; it needs a ``DatasetBuild``, which the composition root
    supplies.

    ``run`` is Tier 1 and ``report`` scores it. ``episodes`` is Tier 2: it
    runs every frozen episode and writes its own tier ``"2"`` run, with
    invariant rows and no scored cases (SIMULATION §8.3).
    """

    def __init__(
        self,
        settings: SimulationSettings,
        clock: ClockPort,
        store: DatasetStorePort,
        model: RoleModelPort,
        sources: tuple[SourceRecord, ...],
        tutor: TutorClientPort | None,
        role: TutorRolePort,
        roster: TutorRoster,
        errors: TextIO,
        build: DatasetBuild | None = None,
        progress: CommandProgress | None = None,
    ) -> None:
        self._settings = settings
        self._build = build
        self._progress = progress
        self._clock = clock
        self._store = store
        self._model = model
        self._sources = sources
        self._tutor = tutor
        self._role = role
        self._roster = roster
        self._errors = errors

    def dispatch(self, command: str) -> int:
        """Run one command. An unknown name is a usage error."""
        if command == "build":
            return self._built()
        if command == "realise":
            return self._realise()
        if command == "freeze":
            return self._freeze()
        if command == "verify":
            return self._verify()
        if command == "run":
            return self._run()
        if command == "episodes":
            return self._episodes()
        if command == "report":
            return self._report()
        self._errors.write(f"tutor_sim: {command} is not a command\n")
        return 2

    def _built(self) -> int:
        if self._build is None:
            self._errors.write("tutor_sim: build needs the source fetch\n")
            return 1
        try:
            summary = self._build.run()
        except (ValueError, OSError) as exc:  # a digest, cache or content fault
            self._errors.write(f"tutor_sim: {exc}\n")
            return 1
        if self._progress is None:
            self._errors.write(f"tutor_sim: {summary.line()}\n")
        else:
            self._progress.finish(summary.line())
        return 0

    def _verify(self) -> int:
        tree = self._verified()
        if tree is None:
            return 1
        self._finish(f"manifest verified: every file in {tree}/ matches its digest")
        return 0

    def _start(self, total: int) -> None:
        if self._progress is not None:
            self._progress.start(total)

    def _step(self, detail: str) -> None:
        if self._progress is not None:
            self._progress.step(detail)

    def _finish(self, summary: str) -> None:
        if self._progress is not None:
            self._progress.finish(summary)

    def _pupil(self) -> PupilPrompt:
        """The persona cards build wrote. They are always public."""
        cards = PersonaCardFile().load(self._root() / "public" / "personas")
        return PupilPrompt(cards)

    def _realise(self) -> int:
        try:
            plan = PlanFile().load(self._root() / "plan.json")
        except FileNotFoundError as exc:
            self._errors.write(f"tutor_sim: {exc}\n")
            return 1
        index = PayloadIndex(plan.payloads)
        realiser = PupilRealiser(
            self._model, ConstructionCheck(), NoiseTransformer(), self._pupil()
        )
        realised: list[StimulusCase] = []
        self._start(len(plan.cases))
        try:
            for offset, case in enumerate(plan.cases):
                realised.append(
                    realiser.realise(
                        case, index.text(case.payload_id), plan.seed + offset
                    )
                )
                self._step(f"{case.case_id} {case.intent}")
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
        writer.write("episodes/plan.jsonl", EpisodePlanFile().body(plan.episodes), tree)
        ActiveTreeFile().write(self._root(), tree)
        discarded = sum(1 for case in cases if case.construction.discarded)
        self._finish(
            f"realised {len(cases)} cases into {tree}/stimuli "
            f"({discarded} discarded: payload not copied)"
        )
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
            for relative in (
                "stimuli/test.jsonl",
                "stimuli/dev.jsonl",
                "discards.json",
                "episodes/plan.jsonl",
            )
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
        self._finish(f"froze {len(cases)} cases: {tree}/manifest.json")
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
        cases = self._read(tree, "stimuli/test.jsonl")
        self._start(len(cases))
        try:
            for case in cases:
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
                        failure=record.failure,
                    )
                )
                if record.failure is not None:
                    self._errors.write(
                        f"tutor_sim: {record.case_id} errored at "
                        f"{record.failure.step}: HTTP {record.failure.http_status} "
                        f"{record.failure.kind or 'unknown status'}\n"
                    )
                self._step(f"{case.case_id} {case.intent}")
        except (CampaignAbort, PolicyMismatch) as exc:
            self._errors.write(f"tutor_sim: {exc}\n")
            return 1
        rows = tuple(recorded)
        CampaignFile().write(self._settings.evidence_dir / "campaign.jsonl", rows)
        ObservationFile().write(
            self._settings.evidence_dir / "observations.jsonl",
            self._observations(rows),
        )
        errored = sum(1 for row in rows if row.errored)
        self._finish(
            f"ran {len(rows)} Tier 1 cases ({errored} errored): "
            "evidence/campaign.jsonl, evidence/observations.jsonl"
        )
        return 0

    def _episodes(self) -> int:
        tutor = self._tutor
        if tutor is None:
            self._errors.write("tutor_sim: episodes needs a tutor client\n")
            return 1
        tree = self._verified()
        if tree is None:
            return 1
        try:
            specs = EpisodePlanFile().read(self._root() / tree / "episodes/plan.jsonl")
        except (FileNotFoundError, DuplicateEpisode) as exc:
            self._errors.write(f"tutor_sim: {exc}\n")
            return 1
        if not specs:
            self._errors.write("tutor_sim: the frozen plan has no episodes\n")
            return 1
        manifest = ManifestFile().load(self._root() / tree / "manifest.json")
        run_id = self._run_id()
        runs = RunDirectory(self._settings.evidence_dir)
        transcripts = TranscriptFile(runs.path(run_id) / "transcripts")
        learners = SimulationNamespace()
        pupil = self._pupil()
        facts: list[InvariantFacts] = []
        self._start(len(specs))
        try:
            for spec in specs:
                runner = EpisodeRunner(
                    tutor,
                    self._roster.role(spec.tutor_role),
                    self._model,
                    ModeGuard(),
                    transcripts,
                )
                record = runner.run(
                    spec,
                    learners.learner_id(spec.persona_id),
                    "tutor-sim",
                    pupil.persona(spec.persona_id),
                    manifest.policy_version,
                )
                facts.extend(record.facts)
                self._step(spec.episode_id)
        except (
            CampaignAbort,
            PolicyMismatch,
            UnknownTutorRole,
            UnknownPersona,
        ) as exc:
            self._errors.write(f"tutor_sim: {exc}\n")
            return 1
        used: list[str] = []
        for item in facts:
            for source in item.observation.sources:
                if source not in used:
                    used.append(source)
        report = ReportBuilder().build(
            run_id,
            manifest.dataset_version,
            f"simulated:{manifest.dataset_version}",
            self._sources,
            tuple(used),
            (),
            tuple(facts),
        )
        runs.write(report, "2", self._clock.now())
        self._finish(f"ran {len(specs)} Tier 2 episodes: run {run_id}")
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
            f"simulated:{manifest.dataset_version}",
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
        runs = RunDirectory(self._settings.evidence_dir)
        runs.path(report.run_id).mkdir(parents=True, exist_ok=True)
        ResultFile().write(
            runs.path(report.run_id) / "results.jsonl",
            tuple(item.result for item in request.scored),
        )
        runs.write(report, "1", self._clock.now())
        self._finish(
            f"scored {len(request.scored)} cases: run {report.run_id} "
            f"(licence {report.licence_status})"
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
