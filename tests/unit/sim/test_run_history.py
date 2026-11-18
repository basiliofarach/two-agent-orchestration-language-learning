"""Every Tier 1 run keeps its own directory; ``report`` scores the latest one."""

import io
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from tests.support.persona_files import PersonaFiles
from tests.unit.sim.test_kernel import OfflineSettings, PinnedSource
from tests.unit.sim.test_simulation_campaign import ScriptedTutor, _case

from tutor_sim.adapters.file_dataset_store import FileDatasetStore
from tutor_sim.adapters.frozen_clock import FrozenClock
from tutor_sim.adapters.role_model import EchoRoleModel
from tutor_sim.application.commands import CampaignCommands, CampaignFile
from tutor_sim.application.realise import RealisePlan
from tutor_sim.application.roles import AbsentTutor, TutorRoster
from tutor_sim.application.run_files import LatestTier1Run, RunDirectory
from tutor_sim.domain.models.observation import Tier1Pointer
from tutor_sim.settings import SimulationSettings

_FIRST = datetime(2026, 11, 18, 9, 0, 0, tzinfo=UTC)
_SECOND = datetime(2026, 11, 19, 9, 0, 0, tzinfo=UTC)


class RosterFailsAfter(ScriptedTutor):
    """Reads the roster ``n`` times, then the API stops answering."""

    def __init__(self, n: int) -> None:
        super().__init__()
        self._left = n

    def learners(self):  # type: ignore[no-untyped-def]
        if self._left == 0:
            self.learners_kind = "errored"
        self._left -= 1
        return super().learners()


class Campaign:
    """Two frozen cases and the commands that run them."""

    def __init__(self, tmp_path: Path) -> None:
        self.settings = OfflineSettings().build(tmp_path, True)
        dataset = self.settings.dataset_dir
        plan = RealisePlan(
            dataset_version="sim-dataset/0.1.0",
            policy_version="prototype-2",
            seed=1,
            cases=(_case("c1"), _case("c2")),
            payloads=(),
        )
        dataset.mkdir(parents=True, exist_ok=True)
        (dataset / "plan.json").write_text(plan.model_dump_json(), encoding="utf-8")
        PersonaFiles().write(dataset)
        self.errors = io.StringIO()
        setup = self.commands(ScriptedTutor(), _FIRST)
        assert setup.dispatch("realise") == 0
        assert setup.dispatch("freeze") == 0

    def commands(
        self,
        client: ScriptedTutor,
        when: datetime,
        settings: SimulationSettings | None = None,
    ) -> CampaignCommands:
        return CampaignCommands(
            settings or self.settings,
            FrozenClock(when),
            FileDatasetStore(self.settings.dataset_dir),
            EchoRoleModel(),
            (PinnedSource().record(),),
            client,
            AbsentTutor(),
            TutorRoster(()),
            self.errors,
        )

    def runs(self) -> Path:
        return self.settings.evidence_dir / "runs"

    def latest(self) -> str | None:
        return LatestTier1Run(self.settings.evidence_dir).run_id()


class TestRunDirectories:
    def test_a_second_run_does_not_overwrite_the_first(self, tmp_path: Path) -> None:
        campaign = Campaign(tmp_path)
        assert campaign.commands(ScriptedTutor(), _FIRST).dispatch("run") == 0
        assert campaign.commands(ScriptedTutor(), _SECOND).dispatch("run") == 0
        first = campaign.runs() / "run-20261118T090000"
        second = campaign.runs() / "run-20261119T090000"
        for directory in (first, second):
            lines = CampaignFile().read(directory / "campaign.jsonl")
            assert [line.case_id for line in lines] == ["c1", "c2"]
            assert (directory / "observations.jsonl").is_file()
        assert campaign.latest() == "run-20261119T090000"
        assert not (campaign.settings.evidence_dir / "campaign.jsonl").exists()

    def test_two_runs_in_the_same_second_get_numbered_directories(
        self, tmp_path: Path
    ) -> None:
        campaign = Campaign(tmp_path)
        for _ in range(3):
            assert campaign.commands(ScriptedTutor(), _FIRST).dispatch("run") == 0
        names = sorted(path.name for path in campaign.runs().iterdir())
        assert names == [
            "run-20261118T090000",
            "run-20261118T090000-2",
            "run-20261118T090000-3",
        ]
        assert campaign.latest() == "run-20261118T090000-3"


class TestAbortedRun:
    def test_an_aborted_run_keeps_the_cases_it_finished(self, tmp_path: Path) -> None:
        campaign = Campaign(tmp_path)
        assert campaign.commands(ScriptedTutor(), _FIRST).dispatch("run") == 0
        assert campaign.commands(RosterFailsAfter(1), _SECOND).dispatch("run") == 1
        aborted = campaign.runs() / "run-20261119T090000"
        lines = CampaignFile().read(aborted / "campaign.jsonl")
        assert [line.case_id for line in lines] == ["c1"]
        assert not (aborted / "observations.jsonl").exists()
        assert "run-20261119T090000/campaign.jsonl" in campaign.errors.getvalue()
        assert campaign.latest() == "run-20261118T090000"


class TestReportPicksARun:
    def test_report_scores_the_latest_run_into_its_own_directory(
        self, tmp_path: Path
    ) -> None:
        campaign = Campaign(tmp_path)
        assert campaign.commands(ScriptedTutor(), _FIRST).dispatch("run") == 0
        assert campaign.commands(ScriptedTutor(), _SECOND).dispatch("run") == 0
        assert campaign.commands(ScriptedTutor(), _SECOND).dispatch("report") == 0
        scored = campaign.runs() / "run-20261119T090000"
        assert (scored / "report.json").is_file()
        assert (scored / "summary.json").is_file()
        assert (scored / "results.jsonl").is_file()
        assert not (campaign.runs() / "run-20261118T090000" / "report.json").exists()
        assert sorted(path.name for path in campaign.runs().iterdir()) == [
            "run-20261118T090000",
            "run-20261119T090000",
        ]

    def test_a_named_run_is_scored_instead_of_the_latest(self, tmp_path: Path) -> None:
        campaign = Campaign(tmp_path)
        assert campaign.commands(ScriptedTutor(), _FIRST).dispatch("run") == 0
        assert campaign.commands(ScriptedTutor(), _SECOND).dispatch("run") == 0
        named = campaign.settings.model_copy(update={"run_id": "run-20261118T090000"})
        report = campaign.commands(ScriptedTutor(), _SECOND, named)
        assert report.dispatch("report") == 0
        assert (campaign.runs() / "run-20261118T090000" / "report.json").is_file()
        assert not (campaign.runs() / "run-20261119T090000" / "report.json").exists()

    def test_an_unfinished_run_is_not_scored(self, tmp_path: Path) -> None:
        campaign = Campaign(tmp_path)
        assert campaign.commands(RosterFailsAfter(1), _FIRST).dispatch("run") == 1
        named = campaign.settings.model_copy(update={"run_id": "run-20261118T090000"})
        assert campaign.commands(ScriptedTutor(), _FIRST, named).dispatch("report") == 1
        assert "run-20261118T090000 did not finish" in campaign.errors.getvalue()

    def test_a_run_missing_its_campaign_is_not_scored(self, tmp_path: Path) -> None:
        campaign = Campaign(tmp_path)
        assert campaign.commands(ScriptedTutor(), _FIRST).dispatch("run") == 0
        (campaign.runs() / "run-20261118T090000" / "campaign.jsonl").unlink()
        assert campaign.commands(ScriptedTutor(), _FIRST).dispatch("report") == 1
        assert "run-20261118T090000 did not finish" in campaign.errors.getvalue()

    def test_an_unknown_run_is_not_scored(self, tmp_path: Path) -> None:
        campaign = Campaign(tmp_path)
        named = campaign.settings.model_copy(update={"run_id": "run-20000101T000000"})
        assert campaign.commands(ScriptedTutor(), _FIRST, named).dispatch("report") == 1
        assert "run-20000101T000000 did not finish" in campaign.errors.getvalue()

    def test_with_no_finished_run_there_is_nothing_to_score(
        self, tmp_path: Path
    ) -> None:
        campaign = Campaign(tmp_path)
        assert campaign.commands(ScriptedTutor(), _FIRST).dispatch("report") == 1
        assert "no campaign results" in campaign.errors.getvalue()


class TestRunIds:
    @pytest.mark.parametrize(
        "value", ["../etc", "run-1", "latest", "run-20261118T090000/x", ""]
    )
    def test_a_run_id_that_is_not_a_run_directory_name_is_refused(
        self, value: str
    ) -> None:
        with pytest.raises(ValidationError):
            SimulationSettings(run_id=value)
        with pytest.raises(ValidationError):
            Tier1Pointer(run_id=value)

    def test_the_pointer_is_frozen_and_forbids_extra_fields(self) -> None:
        pointer = Tier1Pointer(run_id="run-20261118T090000-2")
        with pytest.raises(ValidationError):
            pointer.run_id = "run-20261118T090000"  # type: ignore[misc]
        with pytest.raises(ValidationError):
            Tier1Pointer.model_validate({"run_id": "run-20261118T090000", "x": 1})

    def test_no_pointer_means_no_latest_run(self, tmp_path: Path) -> None:
        assert LatestTier1Run(tmp_path).run_id() is None

    def test_claiming_an_id_creates_its_directory(self, tmp_path: Path) -> None:
        runs = RunDirectory(tmp_path)
        assert runs.claim("run-20261118T090000") == "run-20261118T090000"
        assert runs.path("run-20261118T090000").is_dir()
        assert runs.claim("run-20261118T090000") == "run-20261118T090000-2"


class CountingTutor(ScriptedTutor):
    """Counts the turns it is sent."""

    def __init__(self) -> None:
        super().__init__()
        self.submitted = 0

    def submit(self, session_id, learner_id, prompt, fields):  # type: ignore[no-untyped-def]
        self.submitted += 1
        return super().submit(session_id, learner_id, prompt, fields)


_ABORTED = "run-20261118T090000"


class TestResume:
    def _aborted(self, tmp_path: Path) -> Campaign:
        campaign = Campaign(tmp_path)
        assert campaign.commands(RosterFailsAfter(1), _FIRST).dispatch("run") == 1
        return campaign

    def _resume(self, campaign: Campaign, client: ScriptedTutor, run_id: str) -> int:
        named = campaign.settings.model_copy(update={"run_id": run_id})
        return campaign.commands(client, _SECOND, named).dispatch("run")

    def test_a_resumed_run_sends_only_the_cases_it_has_not_recorded(
        self, tmp_path: Path
    ) -> None:
        campaign = self._aborted(tmp_path)
        client = CountingTutor()
        assert self._resume(campaign, client, _ABORTED) == 0
        assert client.submitted == 1
        directory = campaign.runs() / _ABORTED
        lines = CampaignFile().read(directory / "campaign.jsonl")
        assert [line.case_id for line in lines] == ["c1", "c2"]
        observations = (directory / "observations.jsonl").read_text(encoding="utf-8")
        assert observations.count("\n") == 2
        assert campaign.latest() == _ABORTED
        assert sorted(path.name for path in campaign.runs().iterdir()) == [_ABORTED]
        assert (
            "resuming run-20261118T090000: 1 of 2 cases" in campaign.errors.getvalue()
        )

    def test_a_resumed_run_can_be_resumed_again_after_another_abort(
        self, tmp_path: Path
    ) -> None:
        campaign = self._aborted(tmp_path)
        assert self._resume(campaign, RosterFailsAfter(0), _ABORTED) == 1
        assert self._resume(campaign, ScriptedTutor(), _ABORTED) == 0
        lines = CampaignFile().read(campaign.runs() / _ABORTED / "campaign.jsonl")
        assert [line.case_id for line in lines] == ["c1", "c2"]

    def test_a_finished_run_is_not_resumed(self, tmp_path: Path) -> None:
        campaign = Campaign(tmp_path)
        assert campaign.commands(ScriptedTutor(), _FIRST).dispatch("run") == 0
        client = CountingTutor()
        assert self._resume(campaign, client, _ABORTED) == 1
        assert client.submitted == 0
        assert f"run {_ABORTED} already finished" in campaign.errors.getvalue()

    def test_a_run_with_no_campaign_is_not_resumed(self, tmp_path: Path) -> None:
        campaign = Campaign(tmp_path)
        assert self._resume(campaign, CountingTutor(), _ABORTED) == 1
        assert f"run {_ABORTED} has no campaign to resume" in campaign.errors.getvalue()
        assert not (campaign.runs() / _ABORTED).exists()

    def test_a_run_from_another_split_is_not_resumed(self, tmp_path: Path) -> None:
        campaign = self._aborted(tmp_path)
        trail = campaign.runs() / _ABORTED / "campaign.jsonl"
        trail.write_text(
            trail.read_text(encoding="utf-8").replace('"c1"', '"c-zz"'),
            encoding="utf-8",
        )
        client = CountingTutor()
        assert self._resume(campaign, client, _ABORTED) == 1
        assert client.submitted == 0
        assert "c-zz is not in the frozen test split" in campaign.errors.getvalue()

    def test_a_line_cut_off_when_the_process_died_is_dropped_and_rerun(
        self, tmp_path: Path
    ) -> None:
        campaign = self._aborted(tmp_path)
        trail = campaign.runs() / _ABORTED / "campaign.jsonl"
        with trail.open("a", encoding="utf-8") as handle:
            handle.write('{"case_id": "c2", "err')
        client = CountingTutor()
        assert self._resume(campaign, client, _ABORTED) == 0
        assert client.submitted == 1
        lines = CampaignFile().read(trail)
        assert [line.case_id for line in lines] == ["c1", "c2"]
        assert "dropped an unfinished last line" in campaign.errors.getvalue()

    def test_a_damaged_line_before_the_last_is_refused(self, tmp_path: Path) -> None:
        campaign = Campaign(tmp_path)
        assert campaign.commands(RosterFailsAfter(1), _FIRST).dispatch("run") == 1
        trail = campaign.runs() / _ABORTED / "campaign.jsonl"
        trail.write_text("not json\n" + trail.read_text(encoding="utf-8"), "utf-8")
        assert self._resume(campaign, CountingTutor(), _ABORTED) == 1
        assert (
            f"run {_ABORTED} has a damaged campaign line" in campaign.errors.getvalue()
        )

    def test_a_blank_line_in_the_campaign_is_ignored(self, tmp_path: Path) -> None:
        campaign = self._aborted(tmp_path)
        trail = campaign.runs() / _ABORTED / "campaign.jsonl"
        trail.write_text("\n" + trail.read_text(encoding="utf-8"), "utf-8")
        client = CountingTutor()
        assert self._resume(campaign, client, _ABORTED) == 0
        assert client.submitted == 1


class TestPrintedPaths:
    def test_the_finished_run_names_the_directory_it_wrote(
        self, tmp_path: Path
    ) -> None:
        from tutor_sim.application.progress import CommandProgress

        campaign = Campaign(tmp_path)
        shown = io.StringIO()
        commands = CampaignCommands(
            campaign.settings,
            FrozenClock(_FIRST),
            FileDatasetStore(campaign.settings.dataset_dir),
            EchoRoleModel(),
            (PinnedSource().record(),),
            ScriptedTutor(),
            AbsentTutor(),
            TutorRoster(()),
            campaign.errors,
            None,
            CommandProgress(shown),
        )
        assert commands.dispatch("run") == 0
        assert str(campaign.runs() / _ABORTED) in shown.getvalue()

    def test_an_aborted_run_names_the_campaign_file_it_kept(
        self, tmp_path: Path
    ) -> None:
        campaign = Campaign(tmp_path)
        assert campaign.commands(RosterFailsAfter(1), _FIRST).dispatch("run") == 1
        kept = campaign.runs() / _ABORTED / "campaign.jsonl"
        assert f"1 finished cases kept in {kept}" in campaign.errors.getvalue()
