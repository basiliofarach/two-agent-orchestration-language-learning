"""Policy cards and ports the gate tests share."""

from tutor_api.prototype import PrototypeCopy, PrototypePolicyCard
from tutor_core.domain.models.gate_rules import (
    ConflictRuleIds,
    DriftRuleIds,
    PermissionRuleIds,
    SensitivityRuleIds,
)
from tutor_core.domain.policy.policy_card import ArticleMapping, PolicyCard, PolicyRule
from tutor_core.domain.ports.policy_artifact import PolicyArtifactPort


class GateRules:
    """The identifiers ``PrototypeCopy`` binds, so a test and the container agree."""

    def permission(self) -> PermissionRuleIds:
        """The permission rule identifiers."""
        return PrototypeCopy().permission_rules()

    def conflict(self) -> ConflictRuleIds:
        """The conflict rule identifiers."""
        return PrototypeCopy().conflict_rules()

    def sensitivity(self) -> SensitivityRuleIds:
        """The sensitivity rule identifiers."""
        return PrototypeCopy().sensitivity_rules()

    def drift(self) -> DriftRuleIds:
        """The drift rule identifiers."""
        return PrototypeCopy().drift_rules()


class GateCard:
    """The production prototype card, which names every rule the gates cite."""

    def build(self, threshold: str = "0.5") -> PolicyCard:
        """Return the card. ``threshold`` is the conflict rule's statement."""
        return PrototypePolicyCard(PrototypeCopy()).build("policy-gates", threshold)

    def without(self, *rule_ids: str) -> PolicyCard:
        """A card that does not name ``rule_ids``. Gates citing them fail."""
        full = self.build()
        return PolicyCard(
            version="policy-gates-partial",
            allowed_actions=self._keep(full.allowed_actions, rule_ids),
            denied_actions=self._keep(full.denied_actions, rule_ids),
            escalation_rules=self._keep(full.escalation_rules, rule_ids),
            article_mappings=(ArticleMapping(article="14", locus="oversight gates"),),
        )

    def _keep(
        self, rules: tuple[PolicyRule, ...], dropped: tuple[str, ...]
    ) -> tuple[PolicyRule, ...]:
        return tuple(rule for rule in rules if rule.policy_rule_id not in dropped)


class CardPolicy(PolicyArtifactPort):
    """A policy port that returns one card and does not touch a database."""

    def __init__(self, card: PolicyCard) -> None:
        self._card = card

    async def current(self) -> PolicyCard:
        """Return the card this port was given."""
        return self._card

    async def version(self) -> str:
        """Return that card's version."""
        return self._card.version


class BrokenPolicy(PolicyArtifactPort):
    """A policy port whose read fails, as a lost connection would."""

    async def current(self) -> PolicyCard:
        """Fail."""
        msg = "policy card is unreadable"
        raise RuntimeError(msg)

    async def version(self) -> str:
        """Fail."""
        msg = "policy card is unreadable"
        raise RuntimeError(msg)
