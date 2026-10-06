"""Build a verdict whose rule is on the card in force (REQ-POLICY)."""

from tutor_core.domain.models.verdict import GateDecision, GateVerdict
from tutor_core.domain.policy.policy_card import PolicyCard
from tutor_core.domain.policy.rule_lookup import PolicyRuleLookup


class VerdictCitation:
    """Every verdict cites a rule this card version names.

    A rule the card does not name raises. The gate does not catch that: a
    verdict that cites a rule the log cannot resolve is not evidence, so the
    turn fails and rolls back instead (DEC-0005). One instance serves every
    gate; each passes its own name.
    """

    def __init__(self, lookup: PolicyRuleLookup) -> None:
        self._lookup = lookup

    def cite(  # noqa: PLR0913 — the verdict's four fields and the card
        self,
        gate_name: str,
        card: PolicyCard,
        decision: GateDecision,
        rule_id: str,
        reason: str,
    ) -> GateVerdict:
        """Return the verdict, with the identifier resolved on ``card``."""
        resolved = self._lookup.rule(card, rule_id).policy_rule_id
        return GateVerdict(
            gate_name=gate_name,
            decision=decision,
            reason=reason,
            policy_rule_id=resolved,
        )
