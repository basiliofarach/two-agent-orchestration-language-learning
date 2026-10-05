"""A policy rule id does not change meaning between versions."""

import pytest
from tests.support.samples import Samples

from tutor_core.domain.policy.lineage import PolicyRuleLineage, PolicyRuleMeaningChanged
from tutor_core.domain.policy.policy_card import PolicyCard


class LaterCard:
    """A second version of the sample card."""

    def same_meaning(self) -> PolicyCard:
        card = Samples().policy_card()
        return card.model_copy(update={"version": "policy-2"})

    def changed_statement(self) -> PolicyCard:
        card = Samples().policy_card()
        moved = card.allowed_actions[0].model_copy(update={"statement": "open_web"})
        return card.model_copy(
            update={"version": "policy-2", "allowed_actions": (moved,)}
        )

    def changed_article(self) -> PolicyCard:
        card = Samples().policy_card()
        moved = card.allowed_actions[0].model_copy(update={"article": "14"})
        return card.model_copy(
            update={"version": "policy-2", "allowed_actions": (moved,)}
        )

    def allowed_rule_now_denied(self) -> PolicyCard:
        card = Samples().policy_card()
        return card.model_copy(
            update={
                "version": "policy-2",
                "allowed_actions": (),
                "denied_actions": card.denied_actions + card.allowed_actions,
            }
        )


class TestPolicyRuleLineage:
    def test_the_same_statement_may_keep_its_id(self) -> None:
        PolicyRuleLineage().require_stable(
            (Samples().policy_card(),),
            LaterCard().same_meaning(),
        )

    def test_a_changed_statement_needs_a_new_id(self) -> None:
        with pytest.raises(PolicyRuleMeaningChanged, match="changed meaning"):
            PolicyRuleLineage().require_stable(
                (Samples().policy_card(),),
                LaterCard().changed_statement(),
            )

    def test_a_changed_article_needs_a_new_id(self) -> None:
        with pytest.raises(PolicyRuleMeaningChanged, match="changed meaning"):
            PolicyRuleLineage().require_stable(
                (Samples().policy_card(),),
                LaterCard().changed_article(),
            )

    def test_an_allowed_rule_cannot_become_denied_under_its_id(self) -> None:
        with pytest.raises(PolicyRuleMeaningChanged, match="changed meaning"):
            PolicyRuleLineage().require_stable(
                (Samples().policy_card(),),
                LaterCard().allowed_rule_now_denied(),
            )

    def test_a_rule_dropped_from_a_version_is_accepted(self) -> None:
        card = Samples().policy_card()
        later = card.model_copy(update={"version": "policy-2", "escalation_rules": ()})
        PolicyRuleLineage().require_stable((card,), later)

    def test_earlier_versions_that_disagree_are_rejected(self) -> None:
        with pytest.raises(PolicyRuleMeaningChanged, match="changed meaning"):
            PolicyRuleLineage().require_stable(
                (Samples().policy_card(), LaterCard().changed_statement()),
                LaterCard().same_meaning(),
            )

    def test_a_new_id_is_accepted(self) -> None:
        added = Samples().policy_rule("log-version", "record policy_version", "12")
        card = Samples().policy_card()
        later = card.model_copy(
            update={
                "version": "policy-2",
                "allowed_actions": card.allowed_actions + (added,),
            }
        )
        PolicyRuleLineage().require_stable((card,), later)
