"""CEFR-SP, the Grammar Profile, and the fault partition."""

import hashlib
import re
from pathlib import Path

import pytest

from tutor_sim.adapters.pos_tagger import FixtureTagger, UntaggedSentence
from tutor_sim.application.kb_corpus import (
    CefrSpLoader,
    ContentWords,
    FaultPartition,
    GrammarExampleMiner,
    GrammarProfileLoader,
    ItemCountLogWriter,
    KbCorpusBuilder,
    LevelAssigner,
    LevelOrder,
    TargetStructureCheck,
)
from tutor_sim.domain.models.grammar import (
    CefrSpRow,
    CefrSpSentence,
    GrammarItem,
    GrammarProfileRow,
    TaggedSentence,
    TaggedToken,
    WordLevel,
)
from tutor_sim.domain.models.identity import SimulationNamespace
from tutor_sim.domain.ports.pos_tagger import PosTaggerPort


class DigestKey:
    def of(self, row: CefrSpSentence) -> str:
        return hashlib.sha256(row.text.encode()).hexdigest()


class SentenceTags:
    def mapping(self, texts: tuple[str, ...]) -> dict[str, TaggedSentence]:
        return {
            text: TaggedSentence(
                text=text,
                tokens=(TaggedToken(word=text, tag="NN", lemma=text.lower()),),
            )
            for text in texts
        }

    def tagger(self, texts: tuple[str, ...]) -> FixtureTagger:
        return FixtureTagger(self.mapping(texts), "fixture-1")

    def sentence(
        self, sentence_id: str, text: str, level: str, subset: str
    ) -> CefrSpSentence:
        licence = "CC-BY-NC-SA-4.0" if subset == "score" else "CC-BY-SA-3.0"
        return CefrSpSentence(
            sentence_id=sentence_id,
            text=text,
            level=level,  # type: ignore[arg-type]
            subset=subset,  # type: ignore[arg-type]
            licence=licence,
        )


class TestCefrSpSentence:
    def test_whitespace_is_not_a_sentence(self) -> None:
        with pytest.raises(ValueError, match="blank"):
            CefrSpSentence(
                sentence_id="s",
                text=" ",
                level="A1",
                subset="wiki-auto",
                licence="CC-BY-SA-3.0",
            )


class TestCefrSpLoader:
    def test_only_agreed_a1_to_b2_sentences_are_kept(self) -> None:
        rows = (
            CefrSpRow(
                sentence_id="w",
                text=" Cats ",
                level_a="1",
                level_b="A1",
                subset="wiki-auto",
            ),
            CefrSpRow(
                sentence_id="s",
                text="score",
                level_a="A2",
                level_b="A2",
                subset="score",
            ),
            CefrSpRow(
                sentence_id="b1",
                text="b1",
                level_a="B1",
                level_b="B1",
                subset="wiki-auto",
            ),
            CefrSpRow(
                sentence_id="b2",
                text="b2",
                level_a=" b2 ",
                level_b="B2",
                subset="wiki-auto",
            ),
            CefrSpRow(
                sentence_id="mix",
                text="no",
                level_a="A1",
                level_b="A2",
                subset="wiki-auto",
            ),
            CefrSpRow(
                sentence_id="c",
                text="high",
                level_a="C1",
                level_b="C1",
                subset="wiki-auto",
            ),
            CefrSpRow(
                sentence_id="blank",
                text="  ",
                level_a="A1",
                level_b="A1",
                subset="wiki-auto",
            ),
            CefrSpRow(
                sentence_id="news",
                text="no",
                level_a="A1",
                level_b="A1",
                subset="newsela",
            ),
            CefrSpRow(
                sentence_id="odd",
                text="no",
                level_a="pre",
                level_b="pre",
                subset="wiki-auto",
            ),
        )
        kept = CefrSpLoader().load(rows)
        assert [(row.sentence_id, row.level, row.subset) for row in kept] == [
            ("w", "A1", "wiki-auto"),
            ("s", "A2", "score"),
            ("b1", "B1", "wiki-auto"),
            ("b2", "B2", "wiki-auto"),
        ]
        assert kept[0].text == "Cats"
        assert kept[0].licence == "CC-BY-SA-3.0"
        assert kept[1].licence == "CC-BY-NC-SA-4.0"

    def test_an_empty_file_keeps_nothing(self) -> None:
        assert CefrSpLoader().load(()) == ()


class TestGrammarProfileLoader:
    def test_sub_levels_map_onto_bands(self) -> None:
        rows = tuple(
            GrammarProfileRow(
                item_id=sub,
                name=sub,
                cefr_j_level=f" {sub} ",
                pattern=sub,
                regex="NN",
            )
            for sub in ("A1.1", "A2.1", "B1.1", "B2.2")
        )
        items = GrammarProfileLoader().load(rows)
        assert [item.band for item in items] == ["A1", "A2", "B1", "B2"]
        assert items[0].cefr_j_level == "A1.1"

    def test_an_unknown_sub_level_is_refused(self) -> None:
        row = GrammarProfileRow(
            item_id="x", name="x", cefr_j_level="C1.1", pattern="x", regex="NN"
        )
        with pytest.raises(ValueError, match="C1.1"):
            GrammarProfileLoader().load((row,))


class TestGrammarExampleMiner:
    def test_examples_match_the_regex_at_or_below_the_item(self) -> None:
        texts = tuple(f"sentence-{index}" for index in range(6))
        sentences = tuple(
            SentenceTags().sentence(f"id-{index}", text, "A1", "wiki-auto")
            for index, text in enumerate(texts)
        )
        high = SentenceTags().sentence("high", "too-high", "B2", "wiki-auto")
        miss = SentenceTags().sentence("miss", "no-tag-hit", "A1", "wiki-auto")
        tagged = SentenceTags().mapping(texts + ("too-high",))
        tagged["no-tag-hit"] = TaggedSentence(
            text="no-tag-hit",
            tokens=(TaggedToken(word="no", tag="VB", lemma="no"),),
        )
        tagger = FixtureTagger(tagged, "fixture-1")
        item = GrammarItem(
            item_id="g",
            name="noun",
            cefr_j_level="A1.1",
            band="A1",
            pattern="NN",
            regex="NN",
        )
        found = GrammarExampleMiner(tagger).mine((item,), sentences + (high, miss))
        ordered = sorted(sentences, key=DigestKey().of)
        assert tagger.revision() == "fixture-1"
        assert [row.sentence.text for row in found] == [row.text for row in ordered[:5]]
        assert all(row.item_id == "g" for row in found)

    def test_a_regex_that_does_not_compile_fails_the_build(self) -> None:
        sentence = SentenceTags().sentence("id", "cats", "A1", "wiki-auto")
        item = GrammarItem(
            item_id="g",
            name="noun",
            cefr_j_level="A1.1",
            band="A1",
            pattern="(",
            regex="(",
        )
        with pytest.raises(re.error):
            GrammarExampleMiner(SentenceTags().tagger(("cats",))).mine(
                (item,), (sentence,)
            )

    def test_no_items_mines_nothing(self) -> None:
        assert GrammarExampleMiner(SentenceTags().tagger(())).mine((), ()) == ()


class TestKnowledgeBase:
    def test_faults_stay_out_of_the_default_seed(self, tmp_path: Path) -> None:
        namespace = SimulationNamespace()
        sentence = SentenceTags().sentence("id", "cats sit", "A1", "wiki-auto")
        score = SentenceTags().sentence("sc", "score line", "A1", "score")
        item = GrammarItem(
            item_id="g",
            name="noun",
            cefr_j_level="A1.1",
            band="A1",
            pattern="NN",
            regex="NN",
        )
        examples = GrammarExampleMiner(
            SentenceTags().tagger(("cats sit", "score line"))
        ).mine((item,), (sentence, score))
        documents = KbCorpusBuilder(namespace).build(
            (sentence, score), (item,), examples
        )
        seeded = KbCorpusBuilder(namespace).default_seed(documents)
        assert all(document.partition == "default" for document in seeded)
        faults = [document for document in documents if document.partition == "faults"]
        assert [document.fault_kind for document in faults] == [
            "contradiction",
            "contradiction",
            "poisoned_unreviewed",
            "poisoned_approved",
        ]
        assert faults[2].canary == "CANARY-7F3"
        assert faults[2].review_status == "pending"
        grammar = next(document for document in seeded if document.topic_id == "gp-g")
        assert grammar.licence == (
            "custom:unverified AND CC-BY-NC-SA-4.0 AND CC-BY-SA-3.0"
        )
        assert "score line" in grammar.content
        assert (
            grammar.content_sha256
            == hashlib.sha256(grammar.content.encode()).hexdigest()
        )
        passage = next(
            document
            for document in seeded
            if document.topic_id == "cefr-sp-wiki-auto-A1"
        )
        assert passage.level_method == "cefr-sp-annotator-agreement"
        log = ItemCountLogWriter().record((item,))
        path = tmp_path / "items.log"
        ItemCountLogWriter().write(log, path)
        assert path.read_text(encoding="utf-8") == "A1 1\nA2 0\nB1 0\nB2 0\n"

    def test_an_empty_corpus_is_only_the_fault_partition(self) -> None:
        documents = KbCorpusBuilder(SimulationNamespace()).build((), (), ())
        assert ItemCountLogWriter().record(()).counts[0].count == 0
        assert KbCorpusBuilder(SimulationNamespace()).default_seed(documents) == ()
        assert len(FaultPartition(SimulationNamespace()).documents()) == 4

    def test_a_grammar_item_without_examples_keeps_the_profile_licence(
        self,
    ) -> None:
        item = GrammarItem(
            item_id="g",
            name="noun",
            cefr_j_level="A2.1",
            band="A2",
            pattern="NN",
            regex="NN",
        )
        documents = KbCorpusBuilder(SimulationNamespace()).build((), (item,), ())
        grammar = next(
            document for document in documents if document.topic_id == "gp-g"
        )
        assert grammar.licence == "custom:unverified"

    def test_a_wiki_only_grammar_item_adds_the_wiki_licence(self) -> None:
        sentence = SentenceTags().sentence("id", "cats", "A2", "wiki-auto")
        item = GrammarItem(
            item_id="g",
            name="noun",
            cefr_j_level="A2.1",
            band="A2",
            pattern="NN",
            regex="NN",
        )
        examples = GrammarExampleMiner(SentenceTags().tagger(("cats",))).mine(
            (item,), (sentence,)
        )
        documents = KbCorpusBuilder(SimulationNamespace()).build(
            (sentence,), (item,), examples
        )
        grammar = next(
            document for document in documents if document.topic_id == "gp-g"
        )
        assert grammar.licence == "custom:unverified AND CC-BY-SA-3.0"


class TestMeasures:
    def test_coverage_picks_the_lowest_band_at_95_percent(self) -> None:
        words = (
            WordLevel(word="cat", level="A1"),
            WordLevel(word="hypothesis", level="B2"),
            WordLevel(word="quantum", level="C1"),
        )
        assigner = LevelAssigner(words)
        assert assigner.assign("cat cat") == "A1"
        assert assigner.assign("cat cat hypothesis") == "B2"
        assert assigner.assign("quantum") is None
        assert assigner.assign("the !!!") is None
        assert ContentWords().tokens("Cat, cat") == ("cat", "cat")
        assert ContentWords().tokens("cat ") == ("cat",)
        assert ContentWords().tokens("  ") == ()

    def test_the_order_refuses_a_band_outside_a1_to_b2(self) -> None:
        order = LevelOrder()
        assert order.at_or_below("C1", "A1") is False
        assert order.at_or_below("A1", "C1") is False
        assert order.at_or_below("A2", "A1") is False
        assert order.at_or_below("A1", "A2") is True

    def test_a_target_structure_is_a_regex_on_the_tagged_line(self) -> None:
        tagger = SentenceTags().tagger(("cats sit",))
        check = TargetStructureCheck(tagger)
        assert check.contains("cats sit", "NN") is True
        assert check.contains("cats sit", "VBZ") is False

    def test_a_port_without_tag_cannot_be_instantiated(self) -> None:
        incomplete = type("Incomplete", (PosTaggerPort,), {})
        with pytest.raises(TypeError, match="abstract"):
            incomplete()

    def test_an_unknown_fixture_sentence_is_refused(self) -> None:
        with pytest.raises(UntaggedSentence, match="missing"):
            FixtureTagger({}, "fixture-1").tag("missing")
