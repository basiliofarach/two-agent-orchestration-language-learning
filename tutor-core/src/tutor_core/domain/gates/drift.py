"""Drift and anomaly, after generation (REQ-GATES)."""

from tutor_core.domain.gates.citation import VerdictCitation
from tutor_core.domain.models.gate_rules import DriftEnvelope, DriftRuleIds
from tutor_core.domain.models.turn import TurnState
from tutor_core.domain.models.verdict import GateVerdict
from tutor_core.domain.policy.policy_card import PolicyCard
from tutor_core.domain.ports.oversight_gate import OversightGatePort
from tutor_core.domain.ports.policy_artifact import PolicyArtifactPort


class DriftAnomalyGate(OversightGatePort):
    """Pause when retrieval or generation leaves the expected envelope.

    The envelope is a constructor argument. After the card is loaded:

    1. No retrieval or no generated unit on the turn: ``stop``.
    2. Retrieval confidence below its floor, source support below its
       floor, a draft longer than the maximum, or more grammar findings
       than allowed: ``pause``.
    3. Otherwise: ``pass``.
    """

    def __init__(
        self,
        policy: PolicyArtifactPort,
        envelope: DriftEnvelope,
        rules: DriftRuleIds,
    ) -> None:
        self._policy = policy
        self._envelope = envelope
        self._rules = rules
        self._citation = VerdictCitation(self.name())

    def name(self) -> str:
        """The stage name stored with the verdict."""
        return "drift_and_anomaly"

    async def evaluate(self, turn: TurnState) -> GateVerdict:
        """Judge retrieval and generation behaviour. Do not modify ``turn``."""
        card = await self._policy.current()
        try:
            return self._judge(card, turn)
        except Exception:
            return self._citation.cite(
                card,
                "stop",
                self._rules.evaluation_failed,
                "I could not check how this reply was produced, so I stopped.",
            )

    def _judge(self, card: PolicyCard, turn: TurnState) -> GateVerdict:
        retrieved = turn.retrieved
        generated = turn.generated
        if retrieved is None or generated is None:
            msg = "retrieval or generation has not run"
            raise ValueError(msg)
        envelope = self._envelope
        outside = (
            retrieved.confidence < envelope.min_retrieval_confidence
            or generated.support.support_ratio < envelope.min_support_ratio
            or len(generated.output_after_checks) > envelope.max_output_characters
            or len(generated.grammar) > envelope.max_grammar_findings
        )
        if outside:
            return self._citation.cite(
                card,
                "pause",
                self._rules.outside_envelope,
                "This reply is unlike what the tutor usually produces, so I paused.",
            )
        return self._citation.cite(
            card,
            "pass",
            self._rules.within_envelope,
            "This reply is within the expected range.",
        )
