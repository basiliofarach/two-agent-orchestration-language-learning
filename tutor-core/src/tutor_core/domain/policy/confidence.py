"""The conflict threshold, read from a policy rule rather than a literal."""

from tutor_core.domain.policy.policy_card import PolicyCard
from tutor_core.domain.policy.rule_lookup import PolicyRuleLookup


class ConfidenceThreshold:
    """Parse the threshold rule's statement as a float in ``[0, 1]``.

    The statement is the decimal, for example ``0.5``. The conflict gate
    receives that float as a constructor argument and checks it against
    the card on each evaluation (REQ-GATES, REQ-POLICY).
    """

    def parse(self, card: PolicyCard, rule_id: str) -> float:
        """Return the threshold the rule states."""
        statement = PolicyRuleLookup().rule(card, rule_id).statement
        try:
            value = float(statement)
        except ValueError as exc:
            msg = f"policy rule {rule_id} is not a confidence threshold"
            raise ValueError(msg) from exc
        if not 0.0 <= value <= 1.0:
            msg = f"policy rule {rule_id} is outside 0 to 1"
            raise ValueError(msg)
        return value
