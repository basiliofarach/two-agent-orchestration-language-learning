"""Conflict and ambiguity, after retrieval and before generation (REQ-GATES)."""

import math

from tutor_core.domain.gates.citation import VerdictCitation
from tutor_core.domain.gates.contradiction import SnippetContradiction
from tutor_core.domain.models.gate_rules import ConflictRuleIds
from tutor_core.domain.models.turn import TurnState
from tutor_core.domain.models.verdict import GateVerdict
from tutor_core.domain.policy.confidence import ConfidenceThreshold
from tutor_core.domain.policy.policy_card import PolicyCard
from tutor_core.domain.ports.oversight_gate import OversightGatePort
from tutor_core.domain.ports.policy_artifact import PolicyArtifactPort


class ConflictAmbiguityGate(OversightGatePort):
    """Pause before generation when the retrieved context will not support it.

    ``threshold`` is a constructor argument. It is checked against the
    threshold rule on the policy card; a mismatch fails closed. The gate
    holds no language model and no audit sink. It does not modify the turn.

    A card that cannot be loaded raises, as in the permission gate. After
    the card is loaded:

    1. No retrieval on the turn, or a card the threshold does not match: ``stop``.
    2. No snippets: ``pause``. An empty result never falls through.
    3. Two snippets that negate each other: ``pause``. See
       ``SnippetContradiction``.
    4. Confidence below ``threshold``: ``pause``. Equal to the threshold passes.
    5. Otherwise: ``pass``.
    """

    def __init__(
        self,
        policy: PolicyArtifactPort,
        threshold: float,
        rules: ConflictRuleIds,
    ) -> None:
        if isinstance(threshold, bool) or not isinstance(threshold, float):
            msg = "confidence threshold must be a float"
            raise TypeError(msg)
        if not 0.0 <= threshold <= 1.0:
            msg = "confidence threshold must be between 0 and 1"
            raise ValueError(msg)
        self._policy = policy
        self._threshold = threshold
        self._rules = rules
        self._citation = VerdictCitation(self.name())

    def name(self) -> str:
        """The stage name stored with the verdict."""
        return "conflict_and_ambiguity"

    async def evaluate(self, turn: TurnState) -> GateVerdict:
        """Judge the retrieval already on ``turn``. Do not modify it."""
        card = await self._policy.current()
        try:
            return self._judge(card, turn)
        except Exception:
            return self._citation.cite(
                card,
                "stop",
                self._rules.evaluation_failed,
                "I could not check the retrieved material, so I stopped the turn.",
            )

    def _judge(self, card: PolicyCard, turn: TurnState) -> GateVerdict:
        published = ConfidenceThreshold().parse(card, self._rules.threshold)
        if not math.isclose(published, self._threshold, abs_tol=1e-9):
            msg = "confidence threshold does not match the policy card"
            raise ValueError(msg)
        retrieved = turn.retrieved
        if retrieved is None:
            msg = "retrieval has not run"
            raise ValueError(msg)
        if not retrieved.snippets:
            return self._citation.cite(
                card,
                "pause",
                self._rules.empty,
                "I found no reviewed material, so I did not write an answer.",
            )
        if SnippetContradiction().found(retrieved.snippets):
            return self._citation.cite(
                card,
                "pause",
                self._rules.contradiction,
                "The reviewed materials disagree, so I paused for you to choose.",
            )
        if retrieved.confidence < self._threshold:
            return self._citation.cite(
                card,
                "pause",
                self._rules.low_confidence,
                "The reviewed material is too uncertain, so I paused for you.",
            )
        return self._citation.cite(
            card,
            "pass",
            self._rules.sufficient,
            "The reviewed material is consistent and confident enough to answer from.",
        )
