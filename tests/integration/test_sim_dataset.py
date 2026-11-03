"""The dataset build agrees with the policy card and the PII redactor."""

from tutor_api.adapters.checks.pii_redaction import RegexPiiRedactor, StandardPiiSteps
from tutor_api.prototype import PrototypeCopy, PrototypePolicyCard
from tutor_sim.adapters.pos_tagger import FixtureTagger
from tutor_sim.application.cases import PrototypeExpectations
from tutor_sim.application.kb_corpus import (
    CefrSpLoader,
    GrammarExampleMiner,
    GrammarProfileLoader,
    KbCorpusBuilder,
)
from tutor_sim.application.payloads import SyntheticPiiGenerator
from tutor_sim.domain.models.grammar import (
    CefrSpRow,
    GrammarProfileRow,
    TaggedSentence,
    TaggedToken,
)
from tutor_sim.domain.models.identity import SimulationNamespace


class PolicyIds:
    def on_card(self) -> set[str]:
        card = PrototypePolicyCard(PrototypeCopy()).build("prototype-2", "0.5")
        groups = (card.allowed_actions, card.denied_actions, card.escalation_rules)
        return {rule.policy_rule_id for group in groups for rule in group}


class TestDatasetBuild:
    def test_expectation_rule_ids_are_on_the_prototype_card(self) -> None:
        table = PrototypeExpectations().table()
        cited = set(PrototypeExpectations().rule_ids())
        assert cited <= PolicyIds().on_card()
        held = next(row for row in table.rows if row.intent == "I4")
        assert held.expected.rule_id is None
        assert held.expected.rule_ids == ("conflict-empty", "conflict-low-confidence")
        stopped = next(
            row
            for row in table.rows
            if row.intent == "I5" and row.variant == "canonical"
        )
        assert stopped.expected.rule_id == "permission-unvetted-source"

    def test_synthetic_pii_matches_the_redactor_categories(self) -> None:
        redactor = RegexPiiRedactor(StandardPiiSteps().steps())
        expected = {
            "name": "person_name",
            "email": "email",
            "phone": "phone",
            "address": "postal_address",
        }
        for draft in SyntheticPiiGenerator().generate(seed=2, count=8):
            assert draft.pii_kind is not None
            redacted = redactor.redact(draft.text)
            assert expected[draft.pii_kind] in redacted.redacted_categories
            assert draft.pii_value is not None
            assert draft.pii_value not in redacted.text

    def test_agreed_sentences_become_default_documents(self) -> None:
        rows = (
            CefrSpRow(
                sentence_id="s",
                text="cats sit",
                level_a="A1",
                level_b="A1",
                subset="wiki-auto",
            ),
        )
        sentences = CefrSpLoader().load(rows)
        item = GrammarProfileLoader().load(
            (
                GrammarProfileRow(
                    item_id="g",
                    name="noun",
                    cefr_j_level="A1.1",
                    pattern="NN",
                    regex="NN",
                ),
            )
        )
        tagged = TaggedSentence(
            text="cats sit",
            tokens=(TaggedToken(word="cats", tag="NN", lemma="cat"),),
        )
        examples = GrammarExampleMiner(
            FixtureTagger({"cats sit": tagged}, "fixture-1")
        ).mine(item, sentences)
        documents = KbCorpusBuilder(SimulationNamespace()).build(
            sentences, item, examples
        )
        seeded = KbCorpusBuilder(SimulationNamespace()).default_seed(documents)
        assert examples
        assert all(document.partition == "default" for document in seeded)
        assert any(document.topic_id == "gp-g" for document in seeded)
        assert "CANARY-7F3" not in "\n".join(document.content for document in seeded)
