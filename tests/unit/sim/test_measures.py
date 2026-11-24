"""Level fit, pupil level and I2 target structure (SIMULATION §9.5).

Each class is tested alone: the tagger is a fixture, the wordlist and the
Profile are small built workbooks, and the API is a stub.
"""

import io
import zipfile
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError
from tests.support.cefrj_measures import CefrjFetch, CefrjSources, WordlistFixture
from tests.support.grammar_workbook import WordTagger
from tests.unit.sim.test_episode_runner import RecordingTutor
from tests.unit.sim.test_simulation_campaign import _observation

from tutor_sim.adapters.pos_tagger import FixtureTagger
from tutor_sim.application.grammar_profile import WorkbookUnreadable
from tutor_sim.application.kb_corpus import TargetStructureCheck
from tutor_sim.application.measures import (
    CefrjWordlist,
    LemmaKey,
    LevelFit,
    MeasureSources,
    MeasureSummary,
    MeasureUnavailable,
    NearestRank,
    PendingText,
    PersonaLevels,
    ReleasedText,
    RunMeasurer,
    TargetItems,
    Tier1Texts,
    Tier2Texts,
)
from tutor_sim.application.personas import ErrorProfileLoader, PersonaCardBuilder
from tutor_sim.application.progress import CommandProgress
from tutor_sim.domain.models.api_views import RecordView, TurnDetailView
from tutor_sim.domain.models.case import (
    Construction,
    Expected,
    GeneratorStamp,
    StimulusCase,
)
from tutor_sim.domain.models.client_call import DetailCall
from tutor_sim.domain.models.episode import EpisodeTurn
from tutor_sim.domain.models.grammar import TaggedSentence, TaggedToken, WordLevel
from tutor_sim.domain.models.measures import (
    CoverageSummary,
    MeasuredText,
    RunMeasures,
    TargetStructureRow,
)

_PERSONA = "p-a2-es-12_14-01"
_WORDS = (
    WordLevel(word="cat", level="A1"),
    WordLevel(word="play", level="A1"),
    WordLevel(word="wish", level="B1"),
    WordLevel(word="hypothesis", level="B2"),
)


class _Terminal(io.StringIO):
    """A stream that reports itself as a terminal, so the bar is drawn."""

    def isatty(self) -> bool:
        return True


def _tagged(text: str, *tokens: tuple[str, str, str]) -> TaggedSentence:
    return TaggedSentence(
        text=text,
        tokens=tuple(TaggedToken(word=w, tag=t, lemma=lemma) for w, t, lemma in tokens),
    )


def _fit(tagger: object | None = None) -> LevelFit:
    return LevelFit(tagger or WordTagger(), _WORDS, LemmaKey())  # type: ignore[arg-type]


def _measured(**updates: object) -> MeasuredText:
    body: dict[str, object] = {
        "text_id": "c1",
        "kind": "reply",
        "persona_level": "A2",
        "intent": "I2",
        "listed_words": 1,
        "coverage": 1.0,
    }
    body.update(updates)
    return MeasuredText.model_validate(body)


def _stimulus(case_id: str, intent: str, topic: str | None = None) -> StimulusCase:
    return StimulusCase(
        case_id=case_id,
        dataset_version="sim-dataset/0.1.0",
        policy_version="prototype-2",
        split="test",
        persona_id=_PERSONA,
        intent=intent,  # type: ignore[arg-type]
        variant="canonical",
        topic_id=topic,
        expected=Expected(accept=("released_for_approval",), basis="requirement"),
        utterance=f"pupil message {case_id}",
        construction=Construction(
            payload_present=False,
            attempts=1,
            discarded=False,
            payload_placement="none",
        ),
        generator=GeneratorStamp(
            weights_sha="ab" * 32,
            seed=1,
            temperature=0.0,
            template_version="t",
            card_version="c",
        ),
    )


def _personas() -> PersonaLevels:
    return PersonaLevels(PersonaCardBuilder(ErrorProfileLoader()).cards())


class ReadsRecord(RecordingTutor):
    """``GET /turns/{id}`` returns a reply per turn; others are 404."""

    def __init__(self, texts: dict[UUID, str | None]) -> None:
        super().__init__()
        self._texts = texts

    def detail(self, turn_id: UUID) -> DetailCall:
        self.reads.append(turn_id)
        if turn_id not in self._texts:
            return DetailCall(http_status=404, kind="not_found")
        return DetailCall(
            http_status=200,
            kind="ok",
            body=TurnDetailView(
                record=RecordView(output_after_checks=self._texts[turn_id]),
                record_intact=True,
            ),
        )


class TestMeasureModels:
    def test_a_measured_text_is_frozen_and_closed(self) -> None:
        text = _measured()
        with pytest.raises(ValidationError):
            text.coverage = 0.5  # type: ignore[misc]
        with pytest.raises(ValidationError):
            _measured(text="the reply is not kept")

    def test_coverage_is_set_exactly_when_a_listed_word_was_found(self) -> None:
        with pytest.raises(ValidationError, match="listed word"):
            _measured(listed_words=0, coverage=1.0)
        with pytest.raises(ValidationError, match="listed word"):
            _measured(listed_words=2, coverage=None)
        with pytest.raises(ValidationError):
            _measured(coverage=1.5)

    def test_a_target_item_and_its_result_are_set_together(self) -> None:
        with pytest.raises(ValidationError, match="together"):
            _measured(target_item_id="13")
        with pytest.raises(ValidationError, match="together"):
            _measured(target_present=True)
        assert (
            _measured(target_item_id="13", target_present=False).target_present is False
        )

    def test_summary_counts_stay_within_n(self) -> None:
        with pytest.raises(ValidationError):
            CoverageSummary(kind="reply", n=1, unscored=0, at_95=2, at_98=0)
        with pytest.raises(ValidationError):
            CoverageSummary(kind="reply", n=2, unscored=0, at_95=1, at_98=2)
        with pytest.raises(ValidationError):
            TargetStructureRow(k=2, n=1)

    def test_run_measures_are_frozen_and_closed(self) -> None:
        record = RunMeasures(
            run_id="run-1",
            tier="2",
            dataset_version="v",
            tagger_revision="3.2.3",
            wordlist_revision="1.6",
            unreadable=0,
        )
        with pytest.raises(ValidationError):
            record.unreadable = 1  # type: ignore[misc]
        with pytest.raises(ValidationError):
            RunMeasures.model_validate({**record.model_dump(), "reply": "x"})


class TestCefrjWordlist:
    def test_each_word_keeps_its_easiest_level(self) -> None:
        words = {
            w.word: w.level for w in CefrjWordlist().words(WordlistFixture().wordlist())
        }
        assert words["play"] == "A1"
        assert words["wish"] == "B1"
        assert words["i"] == "A1"

    def test_every_spelling_of_a_headword_is_a_word(self) -> None:
        words = {w.word for w in CefrjWordlist().words(WordlistFixture().wordlist())}
        assert {"am", "a"} <= words

    def test_a_multi_word_or_off_scale_entry_is_left_out(self) -> None:
        body = WordlistFixture().wordlist(
            (("run out", "verb", "B1"), ("ubiquity", "noun", "C1"), ("cat", "n", "A1"))
        )
        assert CefrjWordlist().words(body) == (WordLevel(word="cat", level="A1"),)

    def test_a_download_that_is_not_one_workbook_is_refused(self) -> None:
        with pytest.raises(WorkbookUnreadable, match="not a zip"):
            CefrjWordlist().words(b"plain bytes")
        empty = io.BytesIO()
        with zipfile.ZipFile(empty, "w") as archive:
            archive.writestr("README.txt", "no workbook")
        with pytest.raises(WorkbookUnreadable, match="one .xlsx"):
            CefrjWordlist().words(empty.getvalue())


class TestLemmaKey:
    def test_a_form_is_looked_up_by_its_lemma(self) -> None:
        token = TaggedToken(word="played", tag="VVD", lemma="play")
        assert LemmaKey().key(token, frozenset({"play"})) == "play"

    def test_an_unknown_lemma_falls_back_to_the_word(self) -> None:
        token = TaggedToken(word="Cat", tag="NP", lemma="<unknown>")
        assert LemmaKey().key(token, frozenset({"cat"})) == "cat"

    def test_a_tied_lemma_takes_the_first_listed_candidate(self) -> None:
        token = TaggedToken(word="saw", tag="VVD", lemma="saw|see")
        assert LemmaKey().key(token, frozenset({"see"})) == "see"
        assert LemmaKey().key(token, frozenset({"saw", "see"})) == "saw"

    def test_an_unlisted_word_has_no_key(self) -> None:
        token = TaggedToken(word="Ada", tag="NP", lemma="Ada")
        assert LemmaKey().key(token, frozenset({"cat"})) is None


class TestLevelFit:
    def test_coverage_is_the_share_of_listed_words_at_or_below_the_level(
        self,
    ) -> None:
        measured = _fit().measure("t", "reply", "A2", "I1", "cat play wish Ada")
        assert measured.listed_words == 3
        assert measured.coverage == round(2 / 3, 6)
        assert _fit().measure("t", "reply", "B1", None, "cat wish").coverage == 1.0

    def test_forms_count_through_the_tagger_lemma(self) -> None:
        text = "She played"
        tagger = FixtureTagger(
            {text: _tagged(text, ("She", "PP", "she"), ("played", "VVD", "play"))},
            "fixture-1",
        )
        measured = _fit(tagger).measure("t", "reply", "A1", None, text)
        assert measured.listed_words == 1
        assert measured.coverage == 1.0

    def test_a_text_with_no_listed_word_has_no_share(self) -> None:
        measured = _fit().measure("t", "pupil", "A1", None, "Ada Lovelace")
        assert measured.listed_words == 0
        assert measured.coverage is None


class TestTargetItems:
    def _items(self) -> TargetItems:
        return TargetItems(
            {"13": r"\b(a|an)_DT_(a|an)\b"}, TargetStructureCheck(WordTagger())
        )

    def test_a_released_exercise_is_matched_against_its_item(self) -> None:
        hit = self._items().apply(_measured(), "gp-13", "Give me a cat")
        miss = self._items().apply(_measured(), "gp-13", "Give me cats")
        assert (hit.target_item_id, hit.target_present) == ("13", True)
        assert (miss.target_item_id, miss.target_present) == ("13", False)

    def test_only_an_i2_reply_with_a_profile_topic_is_checked(self) -> None:
        items = self._items()
        untouched = (
            items.apply(_measured(intent="I1"), "gp-13", "a cat"),
            items.apply(_measured(kind="pupil"), "gp-13", "a cat"),
            items.apply(_measured(), None, "a cat"),
            items.apply(_measured(), "cefr-sp/A1", "a cat"),
            items.apply(_measured(), "gp-999", "a cat"),
        )
        assert all(item.target_present is None for item in untouched)


class TestMeasureSources:
    def test_without_the_tagger_the_measures_are_refused(self) -> None:
        sources = MeasureSources(CefrjFetch(), CefrjSources().records(), None)
        with pytest.raises(MeasureUnavailable, match="SIM_TREETAGGER_DIR"):
            sources.fit()
        with pytest.raises(MeasureUnavailable, match="SIM_TREETAGGER_DIR"):
            sources.tagger_revision()

    def test_a_source_missing_from_the_catalogue_or_cache_is_refused(self) -> None:
        sources = MeasureSources(CefrjFetch(), (), WordTagger())
        with pytest.raises(MeasureUnavailable, match="does not list cefr-j-wordlist"):
            sources.fit()
        fetch = CefrjFetch()
        del fetch.bodies["cefr-j-wordlist"]
        missing = MeasureSources(fetch, CefrjSources().records(), WordTagger())
        with pytest.raises(MeasureUnavailable, match="not readable from the cache"):
            missing.fit()

    def test_an_unreadable_artefact_is_refused(self) -> None:
        fetch = CefrjFetch()
        fetch.bodies["cefr-j-wordlist"] = b"not a zip"
        fetch.bodies["cefr-j-grammar-profile"] = b"not a zip"
        sources = MeasureSources(fetch, CefrjSources().records(), WordTagger())
        with pytest.raises(MeasureUnavailable, match="not a zip"):
            sources.fit()
        with pytest.raises(MeasureUnavailable, match="not a zip"):
            sources.targets()

    def test_without_the_profile_there_is_no_target_measure(self) -> None:
        sources = MeasureSources(
            CefrjFetch(), CefrjSources().records(profile=False), WordTagger()
        )
        assert sources.targets() is None
        assert sources.revision("cefr-j-grammar-profile") is None
        assert sources.revision("cefr-j-wordlist") == "1.6"

    def test_the_profile_items_and_the_tagger_revision_are_read(self) -> None:
        sources = MeasureSources(CefrjFetch(), CefrjSources().records(), WordTagger())
        items = sources.targets()
        assert items is not None
        assert items.apply(_measured(), "gp-13", "a cat").target_present is True
        assert sources.tagger_revision() == "word-tagger-fixture"


class TestPendingTexts:
    def test_an_unknown_persona_is_refused(self) -> None:
        with pytest.raises(MeasureUnavailable, match="no persona card for p-x"):
            _personas().level("p-x")

    def test_tier_1_measures_benign_messages_and_released_replies(self) -> None:
        stimuli = (
            _stimulus("c1", "I2", "gp-13"),
            _stimulus("c2", "I1"),
            _stimulus("c3", "I8"),
        )
        observations = (
            _observation(case_id="c1", turn_id=UUID(int=1)),
            _observation(case_id="c2", turn_id=UUID(int=2), outcome="held"),
            _observation(case_id="c3", turn_id=UUID(int=3)),
        )
        pending = Tier1Texts(_personas()).pending(stimuli, observations)
        assert [(p.text_id, p.kind) for p in pending] == [
            ("c1", "pupil"),
            ("c2", "pupil"),
            ("c1", "reply"),
        ]
        reply = pending[-1]
        assert (reply.turn_id, reply.text, reply.topic_id) == (
            UUID(int=1),
            None,
            "gp-13",
        )
        assert pending[0].persona_level == "A2"
        assert pending[0].text == "pupil message c1"

    def test_tier_1_refuses_an_observation_outside_the_frozen_split(self) -> None:
        with pytest.raises(MeasureUnavailable, match="c9 is not in the frozen"):
            Tier1Texts(_personas()).pending((), (_observation(case_id="c9"),))

    def test_tier_2_measures_messages_and_the_replies_the_pupil_got(
        self, tmp_path: Path
    ) -> None:
        turns = (
            EpisodeTurn(
                turn_id=UUID(int=1),
                turn_index=0,
                prompt="hi",
                released="hello",
                decision="approve",
            ),
            EpisodeTurn(
                turn_id=UUID(int=2),
                turn_index=1,
                prompt="again",
                released=None,
                decision="none",
            ),
        )
        (tmp_path / "e-1.jsonl").write_text(
            "".join(turn.model_dump_json() + "\n" for turn in turns), encoding="utf-8"
        )
        pending = Tier2Texts(_personas()).pending(tmp_path, (("e-1", _PERSONA),))
        assert [(p.text_id, p.kind, p.text) for p in pending] == [
            ("e-1#0", "pupil", "hi"),
            ("e-1#0", "reply", "hello"),
            ("e-1#1", "pupil", "again"),
        ]

    def test_tier_2_refuses_a_missing_transcript(self, tmp_path: Path) -> None:
        with pytest.raises(MeasureUnavailable, match="no transcript e-2.jsonl"):
            Tier2Texts(_personas()).pending(tmp_path, (("e-2", _PERSONA),))


class TestReleasedText:
    def _pending(self, turn: int | None, text: str | None = None) -> PendingText:
        return PendingText(
            text_id="c1",
            kind="reply",
            persona_level="A2",
            turn_id=None if turn is None else UUID(int=turn),
            text=text,
        )

    def test_a_reply_is_read_from_the_audit_record(self) -> None:
        client = ReadsRecord({UUID(int=1): "a cat"})
        assert ReleasedText(client).read(self._pending(1)) == "a cat"
        assert client.reads == [UUID(int=1)]

    def test_a_given_text_is_not_read_again(self) -> None:
        client = ReadsRecord({})
        assert ReleasedText(client).read(self._pending(1, "kept")) == "kept"
        assert ReleasedText(client).read(self._pending(None)) is None
        assert client.reads == []

    def test_a_missing_or_blank_record_reads_as_none(self) -> None:
        client = ReadsRecord({UUID(int=2): "  ", UUID(int=3): None})
        reader = ReleasedText(client)
        assert reader.read(self._pending(1)) is None
        assert reader.read(self._pending(2)) is None
        assert reader.read(self._pending(3)) is None


class TestSummary:
    def test_nearest_rank_is_a_value_some_text_had(self) -> None:
        rank = NearestRank()
        values = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)
        assert rank.at(values, 0.10) == 0.1
        assert rank.at(values, 0.50) == 0.5
        assert rank.at(values, 0.90) == 0.9
        assert rank.at((0.7,), 0.10) == 0.7
        assert rank.at((), 0.5) is None

    def test_coverage_rows_are_per_level_then_overall(self) -> None:
        texts = (
            _measured(persona_level="A1", coverage=1.0),
            _measured(persona_level="A1", coverage=0.96),
            _measured(persona_level="B1", coverage=0.5),
            _measured(persona_level="B1", listed_words=0, coverage=None),
            _measured(kind="pupil", persona_level="A1"),
        )
        rows = MeasureSummary(NearestRank()).coverage(texts, "reply")
        assert [(r.level, r.n, r.unscored, r.at_95, r.at_98) for r in rows] == [
            ("A1", 2, 0, 2, 1),
            ("B1", 1, 1, 0, 0),
            (None, 3, 1, 2, 1),
        ]
        assert rows[-1].p50 == 0.96
        assert MeasureSummary(NearestRank()).coverage((), "pupil") == ()

    def test_target_rows_count_only_checked_exercises(self) -> None:
        texts = (
            _measured(persona_level="A1", target_item_id="13", target_present=True),
            _measured(persona_level="A1", target_item_id="13", target_present=False),
            _measured(persona_level="B2", target_item_id="21", target_present=True),
            _measured(persona_level="B2"),
        )
        rows = MeasureSummary(NearestRank()).targets(texts)
        assert [(r.level, r.k, r.n) for r in rows] == [
            ("A1", 1, 2),
            ("B2", 1, 1),
            (None, 2, 3),
        ]


class TestRunMeasurer:
    def test_each_text_is_measured_and_an_unreadable_reply_is_counted(self) -> None:
        pending = (
            PendingText(text_id="c1", kind="pupil", persona_level="A1", text="a cat"),
            PendingText(
                text_id="c1",
                kind="reply",
                persona_level="A1",
                intent="I2",
                topic_id="gp-13",
                turn_id=UUID(int=1),
            ),
            PendingText(
                text_id="c2", kind="reply", persona_level="A1", turn_id=UUID(int=2)
            ),
        )
        sources = MeasureSources(CefrjFetch(), CefrjSources().records(), WordTagger())
        run = RunMeasurer(
            sources.fit(),
            sources.targets(),
            ReleasedText(ReadsRecord({UUID(int=1): "Give me a cat"})),
            None,
        ).measure(pending)
        assert run.unreadable == 1
        assert [(t.text_id, t.kind, t.target_present) for t in run.texts] == [
            ("c1", "pupil", None),
            ("c1", "reply", True),
        ]
        assert run.texts[1].coverage == 1.0

    def test_progress_steps_once_per_text_and_no_profile_leaves_targets_unset(
        self,
    ) -> None:
        pending = (
            PendingText(text_id="c1", kind="pupil", persona_level="A1", text="a cat"),
            PendingText(
                text_id="c2", kind="reply", persona_level="A1", turn_id=UUID(int=2)
            ),
        )
        sources = MeasureSources(CefrjFetch(), CefrjSources().records(), WordTagger())
        stream = _Terminal()
        run = RunMeasurer(sources.fit(), None, None, CommandProgress(stream)).measure(
            pending
        )
        assert run.unreadable == 1
        assert [(t.text_id, t.target_present) for t in run.texts] == [("c1", None)]
        assert "2/2 c2" in stream.getvalue()
