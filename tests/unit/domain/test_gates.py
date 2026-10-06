"""Permission and conflict gates. A judging failure stops; the turn is unchanged.

A card that cannot be read is not a judging failure: there is no rule to
cite, so the gate raises and the turn rolls back (DEC-0005).
"""

import inspect

import pytest
from tests.contract.test_port_contracts import OversightGatePortContract
from tests.support.gate_card import BrokenPolicy, CardPolicy, GateCard, GateRules
from tests.support.samples import Samples

from tutor_core.domain.gates.citation import VerdictCitation
from tutor_core.domain.gates.conflict import ConflictAmbiguityGate
from tutor_core.domain.gates.context_permission import ContextPermissionGate
from tutor_core.domain.gates.contradiction import SnippetContradiction
from tutor_core.domain.models.learner import HistoryFieldSet
from tutor_core.domain.models.retrieval import RetrievalResult, Snippet
from tutor_core.domain.policy.confidence import ConfidenceThreshold
from tutor_core.domain.policy.rule_lookup import PolicyRuleLookup
from tutor_core.domain.ports.oversight_gate import OversightGatePort


class Detectors:
    """The collaborators the conflict gate is given, after its rule ids."""

    def all(self) -> tuple[VerdictCitation, ConfidenceThreshold, SnippetContradiction]:
        lookup = PolicyRuleLookup()
        return (
            VerdictCitation(lookup),
            ConfidenceThreshold(lookup),
            SnippetContradiction(),
        )


class Gates:
    """The two gates over one card, with the deployment's rule identifiers."""

    def permission(
        self,
        policy: CardPolicy | BrokenPolicy | None = None,
        fields: tuple[str, ...] = ("proficiency_level", "events"),
    ) -> ContextPermissionGate:
        card = policy if policy is not None else CardPolicy(GateCard().build())
        minimum = HistoryFieldSet.model_validate({"fields": fields})
        return ContextPermissionGate(
            card, minimum, GateRules().permission(), VerdictCitation(PolicyRuleLookup())
        )

    def conflict(
        self,
        threshold: float = 0.5,
        policy: CardPolicy | BrokenPolicy | None = None,
        statement: str = "0.5",
    ) -> ConflictAmbiguityGate:
        card = policy if policy is not None else CardPolicy(GateCard().build(statement))
        return ConflictAmbiguityGate(
            card,
            threshold,
            GateRules().conflict(),
            *Detectors().all(),
        )


class TestContextPermissionGateContract(OversightGatePortContract):
    def port(self) -> OversightGatePort:
        return Gates().permission()


class TestConflictAmbiguityGateContract(OversightGatePortContract):
    def port(self) -> OversightGatePort:
        return Gates().conflict()


class TestHistoryFieldSet:
    def test_an_unknown_field_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="fields"):
            HistoryFieldSet.model_validate({"fields": ("pseudonym",)})

    def test_a_repeated_field_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="listed twice"):
            HistoryFieldSet(fields=("events", "events"))

    def test_an_empty_set_treats_every_request_as_outside(self) -> None:
        empty = HistoryFieldSet(fields=())
        assert empty.outside(("events",)) == ("events",)
        assert empty.admits("events") is False


class TestContextPermissionGate:
    async def test_permission_gate_passes_when_request_is_in_scope(self) -> None:
        turn = Samples().turn()
        verdict = await Gates().permission().evaluate(turn)
        assert verdict.decision == "pass"
        assert verdict.policy_rule_id == GateRules().permission().in_scope
        assert "reviewed material" in verdict.reason

    async def test_permission_gate_stops_when_unvetted_source_would_be_needed(
        self,
    ) -> None:
        turn = Samples().turn()
        turn.requires_unvetted_source = True
        verdict = await Gates().permission().evaluate(turn)
        assert verdict.decision == "stop"
        assert verdict.policy_rule_id == GateRules().permission().unvetted_source

    async def test_permission_gate_stops_when_history_field_outside_minimum_requested(
        self,
    ) -> None:
        turn = Samples().turn()
        turn.requested_history_fields = ("proficiency_level", "pseudonym")
        verdict = await Gates().permission(fields=("proficiency_level",)).evaluate(turn)
        assert verdict.decision == "stop"
        assert (
            verdict.policy_rule_id == GateRules().permission().history_outside_minimum
        )

    async def test_permission_gate_pauses_when_scope_is_indeterminate(self) -> None:
        turn = Samples().turn()
        turn.learner_prompt = None
        verdict = await Gates().permission().evaluate(turn)
        assert verdict.decision == "pause"
        assert verdict.policy_rule_id == GateRules().permission().indeterminate

    async def test_a_blank_prompt_is_indeterminate_even_if_unvetted(self) -> None:
        turn = Samples().turn()
        turn.learner_prompt = Samples().redacted().model_copy(update={"text": "   "})
        turn.requires_unvetted_source = True
        verdict = await Gates().permission().evaluate(turn)
        assert verdict.decision == "pause"

    async def test_permission_gate_raises_when_the_card_cannot_be_read(
        self,
    ) -> None:
        with pytest.raises(RuntimeError, match="unreadable"):
            await Gates().permission(BrokenPolicy()).evaluate(Samples().turn())

    async def test_a_rule_missing_from_the_card_stops_citing_evaluation_failed(
        self,
    ) -> None:
        rules = GateRules().permission()
        policy = CardPolicy(GateCard().without(rules.in_scope))
        verdict = await Gates().permission(policy).evaluate(Samples().turn())
        assert verdict.decision == "stop"
        assert verdict.policy_rule_id == rules.evaluation_failed

    async def test_a_card_without_the_failure_rule_raises_rather_than_cite_it(
        self,
    ) -> None:
        rules = GateRules().permission()
        policy = CardPolicy(GateCard().without(rules.in_scope, rules.evaluation_failed))
        with pytest.raises(ValueError, match="has no rule"):
            await Gates().permission(policy).evaluate(Samples().turn())

    async def test_permission_gate_does_not_mutate_the_turn(self) -> None:
        turn = Samples().turn()
        turn.requested_history_fields = ("pseudonym",)
        before = turn.model_dump()
        await Gates().permission().evaluate(turn)
        assert turn.model_dump() == before

    def test_the_gate_holds_no_retriever_history_or_audit_sink(self) -> None:
        names = set(inspect.signature(ContextPermissionGate).parameters)
        assert names == {"policy", "minimum", "rules", "citation"}
        assert (
            ContextPermissionGate.name(Gates().permission()) == "context_and_permission"
        )


class TestSnippetContradiction:
    def test_a_negation_is_a_contradiction_in_either_order(self) -> None:
        left = Samples().snippet()
        opened = left.model_copy(update={"content": "The library is open."})
        closed = left.model_copy(update={"content": "not The library is open."})
        assert SnippetContradiction().found((opened, closed)) is True
        assert SnippetContradiction().found((closed, opened)) is True

    def test_one_snippet_and_an_unrelated_pair_do_not_contradict(self) -> None:
        snippet = Samples().snippet()
        other = snippet.model_copy(update={"content": "The museum is closed."})
        assert SnippetContradiction().found(()) is False
        assert SnippetContradiction().found((snippet,)) is False
        assert SnippetContradiction().found((snippet, other)) is False


class TestConfidenceThreshold:
    def test_the_statement_is_the_threshold(self) -> None:
        card = GateCard().build("0.25")
        assert (
            ConfidenceThreshold(PolicyRuleLookup()).parse(
                card, GateRules().conflict().threshold
            )
            == 0.25
        )

    def test_a_statement_that_is_not_a_number_raises(self) -> None:
        card = GateCard().build("high")
        with pytest.raises(ValueError, match="not a confidence threshold"):
            ConfidenceThreshold(PolicyRuleLookup()).parse(
                card, GateRules().conflict().threshold
            )

    def test_a_threshold_outside_zero_to_one_raises(self) -> None:
        card = GateCard().build("1.5")
        with pytest.raises(ValueError, match="outside 0 to 1"):
            ConfidenceThreshold(PolicyRuleLookup()).parse(
                card, GateRules().conflict().threshold
            )

    def test_a_missing_rule_raises(self) -> None:
        with pytest.raises(ValueError, match="has no rule"):
            PolicyRuleLookup().rule(GateCard().build(), "missing-rule")


class TestConflictAmbiguityGate:
    def test_the_threshold_must_be_a_float_inside_the_unit_interval(self) -> None:
        policy = CardPolicy(GateCard().build())
        rules = GateRules().conflict()
        with pytest.raises(TypeError, match="float"):
            ConflictAmbiguityGate(policy, True, rules, *Detectors().all())  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="float"):
            ConflictAmbiguityGate(policy, 1, rules, *Detectors().all())  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="between 0 and 1"):
            ConflictAmbiguityGate(policy, 1.5, rules, *Detectors().all())

    async def test_empty_retrieval_pauses(self) -> None:
        turn = Samples().turn()
        turn.retrieved = RetrievalResult(snippets=(), sources=(), confidence=0.0)
        verdict = await Gates().conflict().evaluate(turn)
        assert verdict.decision == "pause"
        assert verdict.policy_rule_id == GateRules().conflict().empty
        assert "no reviewed material" in verdict.reason

    async def test_a_contradiction_pauses(self) -> None:
        from uuid import UUID

        turn = Samples().turn()
        first = (
            Samples().snippet().model_copy(update={"content": "The library is open."})
        )
        second = first.model_copy(
            update={
                "content": "not the library is open.",
                "chunk_id": UUID("00000000-0000-4000-8000-000000000062"),
            }
        )
        turn.retrieved = RetrievalResult(
            snippets=(first, second),
            sources=(first.source,),
            confidence=0.9,
        )
        verdict = await Gates().conflict().evaluate(turn)
        assert verdict.decision == "pause"
        assert verdict.policy_rule_id == GateRules().conflict().contradiction

    async def test_low_confidence_pauses_and_the_threshold_is_the_boundary(
        self,
    ) -> None:
        turn = Samples().turn()
        turn.retrieved = Samples().retrieval().model_copy(update={"confidence": 0.4})
        below = await Gates().conflict(0.5).evaluate(turn)
        assert below.decision == "pause"
        assert below.policy_rule_id == GateRules().conflict().low_confidence
        equal = await Gates().conflict(threshold=0.4, statement="0.4").evaluate(turn)
        assert equal.decision == "pass"

    async def test_sufficient_context_passes(self) -> None:
        verdict = await Gates().conflict(0.5).evaluate(Samples().turn())
        assert verdict.decision == "pass"
        assert verdict.policy_rule_id == GateRules().conflict().sufficient

    async def test_a_threshold_that_disagrees_with_the_card_stops(self) -> None:
        verdict = (
            await Gates()
            .conflict(threshold=0.25, statement="0.5")
            .evaluate(Samples().turn())
        )
        assert verdict.decision == "stop"
        assert verdict.policy_rule_id == GateRules().conflict().evaluation_failed

    async def test_missing_retrieval_stops(self) -> None:
        turn = Samples().turn()
        turn.retrieved = None
        verdict = await Gates().conflict().evaluate(turn)
        assert verdict.decision == "stop"

    async def test_a_failed_card_read_raises(self) -> None:
        with pytest.raises(RuntimeError, match="unreadable"):
            await Gates().conflict(policy=BrokenPolicy()).evaluate(Samples().turn())

    async def test_conflict_gate_does_not_mutate_the_turn(self) -> None:
        turn = Samples().turn()
        before = turn.model_dump()
        await Gates().conflict().evaluate(turn)
        assert turn.model_dump() == before

    def test_the_gate_holds_no_language_model(self) -> None:
        names = set(inspect.signature(ConflictAmbiguityGate).parameters)
        assert "model" not in names
        assert (
            ConflictAmbiguityGate.name(Gates().conflict()) == "conflict_and_ambiguity"
        )


class TestSnippetIdentity:
    """Two snippets may share a source. The contradiction check reads content."""

    def test_whitespace_and_case_do_not_hide_a_negation(self) -> None:
        snippet = Samples().snippet()
        left = snippet.model_copy(update={"content": "  The Library Is Open.  "})
        right = snippet.model_copy(update={"content": "NOT the library is open."})
        assert SnippetContradiction().found((left, right)) is True
        assert isinstance(left, Snippet)
