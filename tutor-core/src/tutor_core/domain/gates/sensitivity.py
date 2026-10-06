"""Sensitivity and high-stakes, after generation (REQ-GATES)."""

from tutor_core.domain.gates.citation import VerdictCitation
from tutor_core.domain.models.gate_rules import SensitivityRuleIds
from tutor_core.domain.models.turn import TurnState
from tutor_core.domain.models.verdict import GateVerdict
from tutor_core.domain.policy.policy_card import PolicyCard
from tutor_core.domain.ports.oversight_gate import OversightGatePort
from tutor_core.domain.ports.policy_artifact import PolicyArtifactPort


class SensitivityHighStakesGate(OversightGatePort):
    """Hold an output that touches a flagged category for the tutor.

    ``flagged_categories`` is a constructor argument: the safety categories
    this deployment treats as high-stakes, for example an assessed
    proficiency. The flags themselves were raised by the output checks and
    are on the turn; this gate reads them and does not re-classify.

    After the card is loaded:

    1. No generated unit on the turn: ``stop``.
    2. The agent refused: ``stop``. A refusal is never delivered unseen.
    3. A flag in a flagged category: ``pause``.
    4. Otherwise: ``pass``.
    """

    def __init__(
        self,
        policy: PolicyArtifactPort,
        flagged_categories: tuple[str, ...],
        rules: SensitivityRuleIds,
        citation: VerdictCitation,
    ) -> None:
        if not flagged_categories:
            msg = "a sensitivity gate with no flagged category passes everything"
            raise ValueError(msg)
        self._policy = policy
        self._flagged = flagged_categories
        self._rules = rules
        self._citation = citation

    def name(self) -> str:
        """The stage name stored with the verdict."""
        return "sensitivity_and_high_stakes"

    async def evaluate(self, turn: TurnState) -> GateVerdict:
        """Judge the generated output on ``turn``. Do not modify it."""
        card = await self._policy.current()
        try:
            return self._judge(card, turn)
        except Exception:
            return self._citation.cite(
                self.name(),
                card,
                "stop",
                self._rules.evaluation_failed,
                "I could not check this reply for sensitive content, so I stopped.",
            )

    def _judge(self, card: PolicyCard, turn: TurnState) -> GateVerdict:
        generated = turn.generated
        if generated is None:
            msg = "generation has not run"
            raise ValueError(msg)
        if generated.refused:
            return self._citation.cite(
                self.name(),
                card,
                "stop",
                self._rules.refused,
                "The tutor refused this request, so I stopped for you to review.",
            )
        flagged = tuple(
            flag for flag in turn.safety_flags if flag.category in self._flagged
        )
        if flagged:
            return self._citation.cite(
                self.name(),
                card,
                "pause",
                self._rules.flagged_category,
                "This reply touches a sensitive topic, so I paused for you.",
            )
        return self._citation.cite(
            self.name(),
            card,
            "pass",
            self._rules.routine,
            "This reply touches no sensitive topic.",
        )
