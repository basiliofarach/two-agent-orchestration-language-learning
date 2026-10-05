"""A policy rule id keeps its meaning across versions (REQ-POLICY)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from tutor_core.domain.policy.policy_card import PolicyCard, PolicyRule

RuleCategory = Literal["allowed_actions", "denied_actions", "escalation_rules"]


class PolicyRuleMeaningChanged(Exception):
    """The same ``policy_rule_id`` names a different rule."""


class RuleMeaning(BaseModel):
    """What one ``policy_rule_id`` names: where it sits, what it says, why.

    The category is part of the meaning. An id that moves from allowed to
    denied keeps its statement and article and reverses its effect.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    category: RuleCategory
    statement: str
    article: str | None


class PolicyRuleLineage:
    """Reject a republished id whose meaning moved.

    Stability is the evidence claim: the log's ``policy_rule_id`` means the
    same rule in every version that carries it. A changed category,
    statement, or article needs a new id. Dropping a rule from a later
    version is allowed; the id is then retired, not reused.
    """

    def require_stable(
        self,
        earlier: tuple[PolicyCard, ...],
        candidate: PolicyCard,
    ) -> None:
        """Raise when ``candidate`` redefines an id already in force."""
        known: dict[str, RuleMeaning] = {}
        for card in earlier:
            self._absorb(known, card)
        self._absorb(known, candidate)

    def _absorb(self, known: dict[str, RuleMeaning], card: PolicyCard) -> None:
        for rule_id, meaning in self._meanings(card):
            prior = known.setdefault(rule_id, meaning)
            if prior != meaning:
                msg = f"policy_rule_id {rule_id} changed meaning; allocate a new id"
                raise PolicyRuleMeaningChanged(msg)

    def _meanings(self, card: PolicyCard) -> tuple[tuple[str, RuleMeaning], ...]:
        sections: tuple[tuple[RuleCategory, tuple[PolicyRule, ...]], ...] = (
            ("allowed_actions", card.allowed_actions),
            ("denied_actions", card.denied_actions),
            ("escalation_rules", card.escalation_rules),
        )
        return tuple(
            (
                rule.policy_rule_id,
                RuleMeaning(
                    category=category,
                    statement=rule.statement,
                    article=rule.article,
                ),
            )
            for category, rules in sections
            for rule in rules
        )
