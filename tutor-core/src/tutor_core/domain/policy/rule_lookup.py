"""Resolve one rule on a frozen card. A missing rule fails closed."""

from tutor_core.domain.policy.policy_card import PolicyCard, PolicyRule


class PolicyRuleLookup:
    """Find a rule by the identifier the log will store (REQ-POLICY)."""

    def rule(self, card: PolicyCard, rule_id: str) -> PolicyRule:
        """Return the rule. Raise when this version does not name it."""
        for item in card.rules():
            if item.policy_rule_id == rule_id:
                return item
        msg = f"policy card {card.version} has no rule {rule_id}"
        raise ValueError(msg)
