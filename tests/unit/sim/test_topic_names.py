"""A pupil asking about a grammar item names it, in its own words.

The plan carries each Grammar Profile topic's name. A benign case aimed
at ``gp-13`` asks about indefinite articles instead of "a grammar point".
A topic without a name (a CEFR-SP sentence topic) adds nothing.
"""

import io
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from tests.support.grammar_workbook import WordTagger, WorkbookFixture
from tests.support.persona_files import PersonaFiles
from tests.unit.sim.test_build import FixtureFetch, MemoryStore, Sources
from tests.unit.sim.test_kernel import OfflineSettings, PinnedSource
from tests.unit.sim.test_pupil_prompt import _cards, _case

from tutor_sim.adapters.file_dataset_store import FileDatasetStore
from tutor_sim.adapters.frozen_clock import FrozenClock
from tutor_sim.adapters.role_model import EchoRoleModel
from tutor_sim.application.build import DatasetBuild
from tutor_sim.application.commands import CampaignCommands
from tutor_sim.application.realise import PlanFile, PupilPrompt, RealisePlan
from tutor_sim.application.roles import AbsentTutor, TutorRoster
from tutor_sim.domain.models.case import TopicName

_ARTICLES = TopicName(topic_id="gp-13", name="INDEFINITE ARTICLES")


def _topical(topic_id: str | None, intent: str = "I2"):  # type: ignore[no-untyped-def]
    return _case(intent=intent).model_copy(update={"topic_id": topic_id})  # type: ignore[arg-type]


class TestTopicName:
    def test_a_topic_name_is_frozen_and_closed(self) -> None:
        with pytest.raises(ValidationError):
            _ARTICLES.name = "x"  # type: ignore[misc]
        with pytest.raises(ValidationError):
            TopicName.model_validate({"topic_id": "gp-1", "name": "x", "level": "A1"})
        with pytest.raises(ValidationError):
            TopicName(topic_id="gp-1", name="")

    def test_a_plan_written_before_topic_names_still_loads(self) -> None:
        plan = RealisePlan.model_validate(
            {"dataset_version": "v", "policy_version": "p", "seed": 0, "cases": []}
        )
        assert plan.topics == ()


class TestPupilPromptTopic:
    def test_a_named_topic_is_the_grammar_point_the_pupil_asks_about(self) -> None:
        user = PupilPrompt(_cards(), (_ARTICLES,)).user(_topical("gp-13"), None)
        assert "The grammar point is: indefinite articles." in user

    def test_an_unnamed_topic_adds_nothing(self) -> None:
        prompt = PupilPrompt(_cards(), (_ARTICLES,))
        assert "grammar point is" not in prompt.user(_topical("cefr-sp-score-A1"), None)
        assert "grammar point is" not in prompt.user(_topical(None), None)

    def test_the_topic_comes_before_a_payload(self) -> None:
        user = PupilPrompt(_cards(), (_ARTICLES,)).user(_topical("gp-13"), "PAYLOAD")
        assert user.index("indefinite articles") < user.index("PAYLOAD")


class TestTopicsThroughTheCampaign:
    def test_the_build_names_every_grammar_topic(self, tmp_path: Path) -> None:
        records, bodies = Sources().all(tmp_path / "public" / "authored")
        body = WorkbookFixture().body()
        profile = Sources().record("cefr-j-grammar-profile", body, False)
        DatasetBuild(
            FixtureFetch({**bodies, "cefr-j-grammar-profile": body}),
            MemoryStore(),
            (*records, profile),
            tmp_path,
            7,
            WordTagger(),
        ).run()
        plan = PlanFile().load(tmp_path / "plan.json")
        assert _ARTICLES in plan.topics
        assert {topic.topic_id for topic in plan.topics} == {"gp-13", "gp-58", "gp-21"}

    def test_pupil_messages_read_the_names_from_the_plan(self, tmp_path: Path) -> None:
        settings = OfflineSettings().build(tmp_path, True)
        plan = RealisePlan(
            dataset_version="sim-dataset/0.1.0",
            policy_version="prototype-2",
            seed=1,
            cases=(
                _topical("gp-13").model_copy(
                    update={"persona_id": "p-a1-es-12_14-01", "case_id": "c1"}
                ),
            ),
            topics=(_ARTICLES,),
        )
        settings.dataset_dir.mkdir(parents=True)
        (settings.dataset_dir / "plan.json").write_text(
            plan.model_dump_json(), encoding="utf-8"
        )
        PersonaFiles().write(settings.dataset_dir)
        commands = CampaignCommands(
            settings,
            FrozenClock(datetime(2026, 1, 1, tzinfo=UTC)),
            FileDatasetStore(settings.dataset_dir),
            EchoRoleModel(),
            (PinnedSource().record(),),
            None,
            AbsentTutor(),
            TutorRoster(()),
            io.StringIO(),
        )
        assert commands.dispatch("pupil-messages") == 0
        stimuli = next(settings.dataset_dir.glob("*/stimuli/test.jsonl"))
        row = json.loads(stimuli.read_text(encoding="utf-8").splitlines()[0])
        assert "indefinite articles" in row["utterance"]
