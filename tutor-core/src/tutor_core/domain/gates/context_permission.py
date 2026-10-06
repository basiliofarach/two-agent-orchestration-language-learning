"""Context and permission, before retrieval (REQ-GATES, DEC-0005)."""

from tutor_core.domain.gates.citation import VerdictCitation
from tutor_core.domain.models.gate_rules import PermissionRuleIds
from tutor_core.domain.models.learner import HistoryFieldSet
from tutor_core.domain.models.turn import TurnState
from tutor_core.domain.models.verdict import GateVerdict
from tutor_core.domain.policy.policy_card import PolicyCard
from tutor_core.domain.ports.oversight_gate import OversightGatePort
from tutor_core.domain.ports.policy_artifact import PolicyArtifactPort


class ContextPermissionGate(OversightGatePort):
    """Stop before a read that the minimum does not allow (REQ-GATES).

    Holds the policy card and the minimum field set — the same
    ``HistoryFieldSet`` the history adapter is bound to, so the gate and the
    read cannot disagree. It holds no retriever, no knowledge base, no
    history port and no audit sink. The gate does not log and does not
    assign to the turn.

    A card that cannot be loaded raises: there is no rule to cite, so the
    turn fails and rolls back. A failure after the card is loaded is
    ``stop``, citing the evaluation-failed rule on that card.

    Order, each of which is reachable:

    1. A prompt that is missing or blank is indeterminate: ``pause``.
    2. A request that would need an unvetted source: ``stop``.
    3. A requested history field outside the minimum: ``stop``.
    4. Otherwise: ``pass``.
    """

    def __init__(
        self,
        policy: PolicyArtifactPort,
        minimum: HistoryFieldSet,
        rules: PermissionRuleIds,
        citation: VerdictCitation,
    ) -> None:
        self._policy = policy
        self._minimum = minimum
        self._rules = rules
        self._citation = citation

    def name(self) -> str:
        """The stage name stored with the verdict."""
        return "context_and_permission"

    async def evaluate(self, turn: TurnState) -> GateVerdict:
        """Judge scope. Do not modify ``turn``."""
        card = await self._policy.current()
        try:
            return self._judge(card, turn)
        except Exception:
            return self._citation.cite(
                self.name(),
                card,
                "stop",
                self._rules.evaluation_failed,
                "I could not check whether this question is in scope, so I stopped.",
            )

    def _judge(self, card: PolicyCard, turn: TurnState) -> GateVerdict:
        prompt = turn.learner_prompt
        if prompt is None or not prompt.text.strip():
            return self._citation.cite(
                self.name(),
                card,
                "pause",
                self._rules.indeterminate,
                "I cannot tell whether this question is in scope, so I paused for you.",
            )
        if turn.requires_unvetted_source:
            return self._citation.cite(
                self.name(),
                card,
                "stop",
                self._rules.unvetted_source,
                "This question needs an unreviewed source, so I stopped.",
            )
        if self._minimum.outside(turn.requested_history_fields):
            return self._citation.cite(
                self.name(),
                card,
                "stop",
                self._rules.history_outside_minimum,
                "This question asks for student history we do not keep, so I stopped.",
            )
        return self._citation.cite(
            self.name(),
            card,
            "pass",
            self._rules.in_scope,
            "This question stays inside the reviewed material and the history we keep.",
        )
