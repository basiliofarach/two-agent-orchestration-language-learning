"""Drift and anomaly, after generation (REQ-GATES)."""

from tutor_core.domain.gates.citation import VerdictCitation
from tutor_core.domain.models.gate_rules import (
    DriftEnvelope,
    DriftRuleIds,
    SessionEnvelope,
)
from tutor_core.domain.models.safety import GeneratedUnit
from tutor_core.domain.models.turn import TurnState
from tutor_core.domain.models.verdict import GateVerdict
from tutor_core.domain.policy.policy_card import PolicyCard
from tutor_core.domain.ports.oversight_gate import OversightGatePort
from tutor_core.domain.ports.policy_artifact import PolicyArtifactPort


class DriftAnomalyGate(OversightGatePort):
    """Pause when retrieval or generation leaves the expected envelope.

    Two envelopes are constructor arguments: one any turn must stay inside,
    and one relative to the session's earlier turns, which REQ-GATES scopes
    drift to. The session's norm is on the turn, summarised before the
    graph ran; this gate reads it and reads nothing else. After the card is
    loaded:

    1. No retrieval or no generated unit on the turn: ``stop``.
    2. Retrieval confidence below its floor, source support below its
       floor, a draft longer than the maximum, or more grammar findings
       than allowed: ``pause``.
    3. The session already holds ``max_flagged_prompts`` high-severity
       prompts; or, once it has ``min_prior_turns`` drafts, this draft's
       support falls more than ``max_support_drop`` below the session
       mean, or it is more than ``max_length_factor`` times the session's
       mean length: ``pause``, citing the session rule.
    4. Otherwise: ``pass``.
    """

    def __init__(
        self,
        policy: PolicyArtifactPort,
        envelope: DriftEnvelope,
        session: SessionEnvelope,
        rules: DriftRuleIds,
        citation: VerdictCitation,
    ) -> None:
        self._policy = policy
        self._envelope = envelope
        self._session = session
        self._rules = rules
        self._citation = citation

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
                self.name(),
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
                self.name(),
                card,
                "pause",
                self._rules.outside_envelope,
                "This reply is unlike what the tutor usually produces, so I paused.",
            )
        if self._outside_session(turn, generated):
            return self._citation.cite(
                self.name(),
                card,
                "pause",
                self._rules.outside_session_envelope,
                "This turn is unlike the earlier turns in this session, so I paused.",
            )
        return self._citation.cite(
            self.name(),
            card,
            "pass",
            self._rules.within_envelope,
            "This reply is within the expected range.",
        )

    def _outside_session(self, turn: TurnState, generated: GeneratedUnit) -> bool:
        baseline = turn.session_baseline
        session = self._session
        if baseline.flagged_prompts >= session.max_flagged_prompts:
            return True
        if baseline.generated_turns < session.min_prior_turns:
            return False
        support = baseline.mean_support_ratio
        length = baseline.mean_output_characters
        return (
            support is not None
            and generated.support.support_ratio < support - session.max_support_drop
        ) or (
            length is not None
            and len(generated.output_after_checks) > length * session.max_length_factor
        )
