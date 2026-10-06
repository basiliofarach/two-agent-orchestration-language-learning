"""Build a verdict whose rule is on the card in force (REQ-POLICY)."""

from tutor_core.domain.models.verdict import GateDecision, GateVerdict
from tutor_core.domain.policy.policy_card import PolicyCard
from tutor_core.domain.policy.rule_lookup import PolicyRuleLookup


class VerdictCitation:
    """Every verdict cites a rule this card version names.

    A rule the card does not name raises. The gate does not catch that: a
    verdict that cites a rule the log cannot resolve is not evidence, so the
    turn fails and rolls back instead (DEC-0005).
    """

    def __init__(self, gate_name: str) -> None:
        self._gate_name = gate_name

    def cite(
        self,
        card: PolicyCard,
        decision: GateDecision,
        rule_id: str,
        reason: str,
    ) -> GateVerdict:
        """Return the verdict, with the identifier resolved on ``card``."""
        resolved = PolicyRuleLookup().rule(card, rule_id).policy_rule_id
        return GateVerdict(
            gate_name=self._gate_name,
            decision=decision,
            reason=reason,
            policy_rule_id=resolved,
        )
