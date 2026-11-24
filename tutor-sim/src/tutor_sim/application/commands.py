"""The operator commands.

build, pupil-messages, freeze, verify, run, episodes, report and measures.
"""

from pathlib import Path
from typing import Literal, TextIO, TypeVar

from pydantic import BaseModel, ConfigDict, ValidationError

from tutor_sim.application.build import DatasetBuild
from tutor_sim.application.episode import (
    DuplicateEpisode,
    EpisodeLine,
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
from tutor_sim.application.measures import (
    MeasureSources,
    MeasureSummary,
    MeasureUnavailable,
    NearestRank,
    PendingText,
    PersonaLevels,
    ReleasedText,
    RunMeasurer,
    Tier1Texts,
    Tier2Texts,
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
from tutor_sim.application.run_files import LatestTier1Run, RunDirectory
from tutor_sim.application.tier1 import (
    CampaignAbort,
    ModeGuard,
    PolicyMismatch,
    Tier1Runner,
)
from tutor_sim.domain.models.case import EpisodeSpec, StimulusCase, TopicName
from tutor_sim.domain.models.identity import SimulationNamespace
from tutor_sim.domain.models.manifest import RoleModelPin
from tutor_sim.domain.models.measures import MeasuredText, RunMeasures
from tutor_sim.domain.models.observation import CampaignLine, Observation
from tutor_sim.domain.models.persona import PersonaCard
from tutor_sim.domain.models.report import CaseResult, SimulationReport
from tutor_sim.domain.models.source import SourceRecord
from tutor_sim.domain.models.storage import DatasetTree
from tutor_sim.domain.ports.clock import ClockPort
from tutor_sim.domain.ports.dataset_store import DatasetStorePort
from tutor_sim.domain.ports.role_model import RoleModelPort
from tutor_sim.domain.ports.tutor_client import TutorClientPort
from tutor_sim.domain.ports.tutor_role import TutorRolePort
from tutor_sim.settings import SimulationSettings


class CampaignCommands:
    """build, pupil-messages, freeze, verify, run, episodes, report, measures.

    ``build`` reads the pinned sources and writes the dataset and
    ``plan.json``; it needs a ``DatasetBuild``, which the composition root
    supplies.

    ``run`` is Tier 1 and ``report`` scores it. ``episodes`` is Tier 2: it
    runs every frozen episode and writes its own tier ``"2"`` run, with
    invariant rows and no scored cases (SIMULATION §8.3).

    ``measures`` reads a finished run's texts through TreeTagger and the
    CEFR-J wordlist and writes ``measures.json`` beside its report
    (SIMULATION §9.5). It needs ``MeasureSources``, which the composition
    root supplies.
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
        measures: MeasureSources | None = None,
    ) -> None:
        self._settings = settings
        self._build = build
        self._measure_sources = measures
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
        if command == "pupil-messages":
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
        if command == "measures":
            return self._measures()
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

    def _start(self, total: int, done: int = 0) -> None:
        if self._progress is not None:
            self._progress.start(total, done)

    def _step(self, detail: str) -> None:
        if self._progress is not None:
            self._progress.step(detail)

    def _finish(self, summary: str) -> None:
        if self._progress is not None:
            self._progress.finish(summary)

    def _pupil(self, topics: tuple[TopicName, ...] = ()) -> PupilPrompt:
        """The persona cards build wrote. They are always public."""
        cards = PersonaCardFile().load(self._root() / "public" / "personas")
        return PupilPrompt(cards, topics)

    def _realise(self) -> int:
        try:
            plan = PlanFile().load(self._root() / "plan.json")
        except FileNotFoundError as exc:
            self._errors.write(f"tutor_sim: {exc}\n")
            return 1
        index = PayloadIndex(plan.payloads)
        realiser = PupilRealiser(
            self._model,
            ConstructionCheck(),
            NoiseTransformer(),
            self._pupil(plan.topics),
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
            f"wrote {len(cases)} pupil messages into {tree}/stimuli "
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
            archived = tuple(
                ManifestFile().load(path)
                for path in sorted(
                    (self._root() / tree / "superseded").glob("*/manifest.json")
                )
            )
        except (OSError, ValidationError) as exc:
            self._errors.write(f"tutor_sim: {exc}\n")
            return 1
        try:
            Freezer(self._clock, self._store).freeze(job, files, existing, archived)
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
        cases = self._read(tree, "stimuli/test.jsonl")
        runs = RunDirectory(self._settings.evidence_dir)
        campaign = CampaignFile()
        opened = self._open_run(runs, campaign, cases)
        if opened is None:
            return 1
        run_id, done = opened
        trail = runs.path(run_id) / "campaign.jsonl"
        recorded: list[CampaignLine] = list(done)
        finished = {line.case_id for line in done}
        self._start(len(cases), len(done))
        try:
            for case in cases:
                if case.case_id in finished:
                    continue
                record = runner.run(
                    case,
                    case.utterance,
                    learners.learner_id(case.persona_id),
                    "tutor-sim",
                )
                line = CampaignLine(
                    case_id=record.case_id,
                    errored=record.errored,
                    observation=record.observation,
                    failure=record.failure,
                )
                recorded.append(line)
                campaign.append(trail, line)
                if record.failure is not None:
                    self._errors.write(
                        f"tutor_sim: {record.case_id} errored at "
                        f"{record.failure.step}: HTTP {record.failure.http_status} "
                        f"{record.failure.kind or 'unknown status'}\n"
                    )
                self._step(f"{case.case_id} {case.intent}")
        except (CampaignAbort, PolicyMismatch) as exc:
            self._errors.write(f"tutor_sim: {exc}\n")
            self._errors.write(
                f"tutor_sim: {len(recorded)} finished cases kept in "
                f"{trail}; the run is not marked latest\n"
            )
            return 1
        rows = tuple(recorded)
        ObservationFile().write(
            runs.path(run_id) / "observations.jsonl", self._observations(rows)
        )
        LatestTier1Run(self._settings.evidence_dir).point(run_id)
        errored = sum(1 for row in rows if row.errored)
        self._finish(
            f"ran {len(rows)} Tier 1 cases ({errored} errored): "
            f"run {run_id} ({runs.path(run_id)})"
        )
        return 0

    def _open_run(
        self,
        runs: RunDirectory,
        campaign: "CampaignFile",
        cases: tuple[StimulusCase, ...],
    ) -> tuple[str, tuple[CampaignLine, ...]] | None:
        """A new run directory, or the named run's recorded cases to skip."""
        run_id = self._settings.run_id
        if run_id is None:
            claimed = runs.claim(self._run_id())
            campaign.write(runs.path(claimed) / "campaign.jsonl", ())
            return (claimed, ())
        trail = runs.path(run_id) / "campaign.jsonl"
        if (runs.path(run_id) / "observations.jsonl").is_file():
            self._errors.write(f"tutor_sim: run {run_id} already finished\n")
            return None
        if not trail.is_file():
            self._errors.write(f"tutor_sim: run {run_id} has no campaign to resume\n")
            return None
        try:
            recovered = campaign.recover(trail)
        except DamagedCampaign:
            self._errors.write(f"tutor_sim: run {run_id} has a damaged campaign line\n")
            return None
        planned = {case.case_id for case in cases}
        for line in recovered.lines:
            if line.case_id not in planned:
                self._errors.write(
                    f"tutor_sim: {line.case_id} is not in the frozen test split\n"
                )
                return None
        if recovered.dropped:
            self._errors.write(
                f"tutor_sim: run {run_id}: dropped an unfinished last line; "
                "that case runs again\n"
            )
        self._errors.write(
            f"tutor_sim: resuming {run_id}: {len(recovered.lines)} of "
            f"{len(cases)} cases already recorded\n"
        )
        return (run_id, recovered.lines)

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
        runs = RunDirectory(self._settings.evidence_dir)
        trail_file = EpisodeTrailFile()
        opened = self._open_episodes(runs, trail_file, specs)
        if opened is None:
            return 1
        run_id, done = opened
        trail = runs.path(run_id) / "episodes.jsonl"
        transcripts = TranscriptFile(runs.path(run_id) / "transcripts")
        learners = SimulationNamespace()
        pupil = self._pupil()
        finished = {line.episode_id for line in done}
        facts: list[InvariantFacts] = [item for line in done for item in line.facts]
        refused = sum(1 for line in done if line.rejected is not None)
        self._start(len(specs), len(done))
        try:
            for spec in specs:
                if spec.episode_id in finished:
                    continue
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
                trail_file.append(
                    trail,
                    EpisodeLine(
                        episode_id=spec.episode_id,
                        facts=record.facts,
                        rejected=record.rejected,
                    ),
                )
                facts.extend(record.facts)
                rejected = record.rejected
                if rejected is not None:
                    refused += 1
                    self._errors.write(
                        f"tutor_sim: {spec.episode_id} ended at turn "
                        f"{rejected.turn_index}: the API refused the pupil's "
                        f"message (HTTP {rejected.http_status} {rejected.kind}, "
                        f"{rejected.characters} characters)\n"
                    )
                self._step(spec.episode_id)
        except (
            CampaignAbort,
            PolicyMismatch,
            UnknownTutorRole,
            UnknownPersona,
        ) as exc:
            self._errors.write(f"tutor_sim: {exc}\n")
            self._errors.write(
                f"tutor_sim: finished episodes kept in {trail}; "
                f"resume with SIM_RUN_ID={run_id}\n"
            )
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
        self._finish(
            f"ran {len(specs)} Tier 2 episodes ({refused} ended by a refused "
            f"message): run {run_id} ({runs.path(run_id)})"
        )
        return 0

    def _open_episodes(
        self,
        runs: RunDirectory,
        trail_file: "EpisodeTrailFile",
        specs: tuple[EpisodeSpec, ...],
    ) -> tuple[str, tuple[EpisodeLine, ...]] | None:
        """A new run directory, or the named run's finished episodes to skip."""
        run_id = self._settings.run_id
        if run_id is None:
            claimed = runs.claim(self._run_id())
            trail_file.write(runs.path(claimed) / "episodes.jsonl", ())
            return (claimed, ())
        trail = runs.path(run_id) / "episodes.jsonl"
        if (runs.path(run_id) / "report.json").is_file():
            self._errors.write(f"tutor_sim: run {run_id} already finished\n")
            return None
        if not trail.is_file():
            self._errors.write(f"tutor_sim: run {run_id} has no episodes to resume\n")
            return None
        try:
            recovered = trail_file.recover(trail)
        except DamagedCampaign:
            self._errors.write(f"tutor_sim: run {run_id} has a damaged episode line\n")
            return None
        planned = {spec.episode_id for spec in specs}
        for line in recovered.lines:
            if line.episode_id not in planned:
                self._errors.write(
                    f"tutor_sim: {line.episode_id} is not in the frozen episode plan\n"
                )
                return None
        if recovered.dropped:
            self._errors.write(
                f"tutor_sim: run {run_id}: dropped an unfinished last line; "
                "that episode runs again\n"
            )
        self._errors.write(
            f"tutor_sim: resuming {run_id}: {len(recovered.lines)} of "
            f"{len(specs)} episodes already recorded\n"
        )
        return (run_id, recovered.lines)

    def _report(self) -> int:
        tree = self._verified()
        if tree is None:
            return 1
        run_id = (
            self._settings.run_id
            or LatestTier1Run(self._settings.evidence_dir).run_id()
        )
        if run_id is None:
            self._errors.write("tutor_sim: no campaign results\n")
            return 1
        runs = RunDirectory(self._settings.evidence_dir)
        try:
            if not (runs.path(run_id) / "observations.jsonl").is_file():
                raise FileNotFoundError(run_id)
            lines = CampaignFile().read(runs.path(run_id) / "campaign.jsonl")
        except FileNotFoundError:
            self._errors.write(f"tutor_sim: run {run_id} did not finish\n")
            return 1
        manifest = ManifestFile().load(self._root() / tree / "manifest.json")
        request = ReportAssembly().request(
            run_id,
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

    def _measures(self) -> int:
        """Measure one finished run, once. Its evidence files are not touched."""
        sources = self._measure_sources
        if sources is None:
            self._errors.write("tutor_sim: measures needs the CEFR-J sources\n")
            return 1
        run_id = self._settings.run_id
        if run_id is None:
            self._errors.write("tutor_sim: measures needs SIM_RUN_ID=<run_id>\n")
            return 1
        runs = RunDirectory(self._settings.evidence_dir)
        run = runs.path(run_id)
        if not (run / "report.json").is_file():
            self._errors.write(f"tutor_sim: run {run_id} has no report yet\n")
            return 1
        if (run / "measures.json").exists():
            self._errors.write(f"tutor_sim: run {run_id} is already measured\n")
            return 1
        tree = self._verified()
        if tree is None:
            return 1
        report = SimulationReport.model_validate_json(
            (run / "report.json").read_text(encoding="utf-8")
        )
        personas = PersonaLevels(self._pupil_cards())
        tier: Literal["1", "2"] = "2"
        try:
            if (run / "campaign.jsonl").is_file():
                tier = "1"
                pending = self._tier1_pending(tree, report, run, personas)
                if self._tutor is None:
                    self._errors.write(
                        "tutor_sim: a Tier 1 run's replies are read from the API; "
                        "measures needs a tutor client\n"
                    )
                    return 1
                reader: ReleasedText | None = ReleasedText(self._tutor)
            else:
                pending = self._tier2_pending(tree, run, personas)
                reader = None
            measurer = RunMeasurer(
                sources.fit(), sources.targets(), reader, self._progress
            )
            measured = measurer.measure(pending)
            tagger = sources.tagger_revision()
        except (MeasureUnavailable, FileNotFoundError, DamagedCampaign) as exc:
            self._errors.write(f"tutor_sim: {exc}\n")
            return 1
        summary = MeasureSummary(NearestRank())
        record = RunMeasures(
            run_id=run_id,
            tier=tier,
            dataset_version=report.dataset_version,
            tagger_revision=tagger,
            wordlist_revision=sources.revision("cefr-j-wordlist") or "unknown",
            profile_revision=sources.revision("cefr-j-grammar-profile"),
            level_fit=summary.coverage(measured.texts, "reply"),
            pupil_level=summary.coverage(measured.texts, "pupil"),
            target_structure=summary.targets(measured.texts),
            unreadable=measured.unreadable,
        )
        MeasureFile().write(run, measured.texts, record)
        self._finish(
            f"measured {len(measured.texts)} texts "
            f"({measured.unreadable} replies unreadable): run {run_id}"
        )
        return 0

    def _tier1_pending(
        self,
        tree: DatasetTree,
        report: SimulationReport,
        run: Path,
        personas: PersonaLevels,
    ) -> tuple[PendingText, ...]:
        """The run must have been scored against the tree frozen now."""
        manifest = ManifestFile().load(self._root() / tree / "manifest.json")
        if report.dataset_version != manifest.dataset_version:
            msg = (
                f"run {report.run_id} was scored against {report.dataset_version}; "
                f"the frozen tree is {manifest.dataset_version}"
            )
            raise MeasureUnavailable(msg)
        lines = CampaignFile().read(run / "campaign.jsonl")
        return Tier1Texts(personas).pending(
            self._read(tree, "stimuli/test.jsonl"), self._observations(lines)
        )

    def _tier2_pending(
        self, tree: DatasetTree, run: Path, personas: PersonaLevels
    ) -> tuple[PendingText, ...]:
        """Texts come from the run's transcripts; personas from the frozen plan."""
        specs = EpisodePlanFile().read(self._root() / tree / "episodes/plan.jsonl")
        persona_of = {spec.episode_id: spec.persona_id for spec in specs}
        episodes: list[tuple[str, str]] = []
        for line in EpisodeTrailFile().read(run / "episodes.jsonl"):
            persona = persona_of.get(line.episode_id)
            if persona is None:
                msg = f"{line.episode_id} is not in the frozen episode plan"
                raise MeasureUnavailable(msg)
            episodes.append((line.episode_id, persona))
        return Tier2Texts(personas).pending(run / "transcripts", tuple(episodes))

    def _pupil_cards(self) -> tuple[PersonaCard, ...]:
        return PersonaCardFile().load(self._root() / "public" / "personas")

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


_Line = TypeVar("_Line", bound=BaseModel)


class JsonlFile:
    """One JSON object per line. An empty sequence writes an empty file."""

    def _recover(
        self, path: Path, model: type[_Line]
    ) -> tuple[tuple[_Line, ...], bool]:
        """Every complete line, and whether a cut-off last line was dropped.

        A process killed mid-write leaves a last line with no newline. That
        line is dropped and the file rewritten, so its unit runs again. Any
        other line that does not parse is damage, not an interruption.
        """
        text = path.read_text(encoding="utf-8")
        raw = text.split("\n")
        tail = raw.pop()
        lines: list[_Line] = []
        for item in raw:
            if not item:
                continue
            try:
                lines.append(model.model_validate_json(item))
            except ValidationError as exc:
                raise DamagedCampaign(path.name) from exc
        if tail:
            self._write(path, tuple(line.model_dump_json() for line in lines))
        return (tuple(lines), bool(tail))

    def _append(self, path: Path, line: BaseModel) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line.model_dump_json() + "\n")

    def _write(self, path: Path, lines: tuple[str, ...]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")

    def _read(self, path: Path) -> tuple[str, ...]:
        if not path.is_file():
            msg = "no campaign results"
            raise FileNotFoundError(msg)
        text = path.read_text(encoding="utf-8")
        return tuple(line for line in text.splitlines() if line)


class DamagedCampaign(Exception):
    """A trail line other than an unfinished last one does not parse.

    Either trail: Tier 1's ``campaign.jsonl`` or Tier 2's ``episodes.jsonl``.
    """


class RecoveredCampaign(BaseModel):
    """The lines a resumed run keeps, and whether a cut-off line was dropped."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    lines: tuple[CampaignLine, ...]
    dropped: bool


class CampaignFile(JsonlFile):
    """Every case, including those that errored and have no observation."""

    def write(self, path: Path, rows: tuple[CampaignLine, ...]) -> None:
        """Replace the file with one line per case."""
        self._write(path, tuple(row.model_dump_json() for row in rows))

    def recover(self, path: Path) -> RecoveredCampaign:
        """Read a run's lines to resume it. A cut-off last case runs again."""
        lines, dropped = self._recover(path, CampaignLine)
        return RecoveredCampaign(lines=lines, dropped=dropped)

    def append(self, path: Path, row: CampaignLine) -> None:
        """Add one finished case, so an aborted run keeps what it ran."""
        self._append(path, row)

    def read(self, path: Path) -> tuple[CampaignLine, ...]:
        """The lines a report scores. A missing file is a command error."""
        return tuple(
            CampaignLine.model_validate_json(line) for line in self._read(path)
        )


class RecoveredEpisodes(BaseModel):
    """The episodes a resumed Tier 2 run keeps, and whether one was cut off."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    lines: tuple[EpisodeLine, ...]
    dropped: bool


class EpisodeTrailFile(JsonlFile):
    """``episodes.jsonl``: one ``EpisodeLine`` per finished episode."""

    def write(self, path: Path, rows: tuple[EpisodeLine, ...]) -> None:
        """Replace the file with one line per episode."""
        self._write(path, tuple(row.model_dump_json() for row in rows))

    def recover(self, path: Path) -> RecoveredEpisodes:
        """Read a run's episodes to resume it. A cut-off last one runs again."""
        lines, dropped = self._recover(path, EpisodeLine)
        return RecoveredEpisodes(lines=lines, dropped=dropped)

    def append(self, path: Path, row: EpisodeLine) -> None:
        """Add one finished episode, so an aborted run keeps what it ran."""
        self._append(path, row)

    def read(self, path: Path) -> tuple[EpisodeLine, ...]:
        """A finished run's episodes, unchanged. A bad line is damage."""
        try:
            return tuple(
                EpisodeLine.model_validate_json(line) for line in self._read(path)
            )
        except ValidationError as exc:
            raise DamagedCampaign(path.name) from exc


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


class MeasureFile:
    """``measures.jsonl`` (one line per text, no text), then ``measures.json``.

    The summary lands last, by atomic rename, so a run with a summary has
    every line behind it.
    """

    def write(
        self, run: Path, texts: tuple[MeasuredText, ...], record: RunMeasures
    ) -> None:
        """Write both files."""
        lines = run / "measures.jsonl"
        partial = lines.with_name(f".{lines.name}.partial")
        partial.write_text(
            "".join(text.model_dump_json() + "\n" for text in texts), encoding="utf-8"
        )
        partial.replace(lines)
        summary = run / "measures.json"
        partial = summary.with_name(f".{summary.name}.partial")
        partial.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        partial.replace(summary)
