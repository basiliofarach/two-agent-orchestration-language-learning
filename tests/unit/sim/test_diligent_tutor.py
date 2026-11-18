"""T1 sees the dashboard a tutor sees, and answers with one action word.

The first campaign sent the role model only the status word. It never saw
the draft, answered with chat, and every decision fell back to ``none``.
"""

import pytest
from tests.unit.sim.test_simulation_campaign import (
    _LEARNER,
    ScriptedTutor,
    _case,
)

from tutor_sim.application.roles import (
    ActionWord,
    DashboardBrief,
    DiligentTutor,
    DiligentTutorCard,
)
from tutor_sim.application.tier1 import Tier1Runner
from tutor_sim.domain.models.tutor_role import DashboardView, TutorDecision
from tutor_sim.domain.ports.role_model import RoleModelPort
from tutor_sim.domain.ports.tutor_role import TutorRolePort


class Prompts(RoleModelPort):
    """Records what the role model was asked, then answers ``reply``."""

    def __init__(self, reply: str) -> None:
        self._reply = reply
        self.asked: list[tuple[str, str]] = []

    def weights_sha(self) -> str:
        return "ab" * 32

    def complete(self, system: str, user: str) -> str:
        self.asked.append((system, user))
        return self._reply


def _held(draft: str | None = "Use 'kick': I kick the ball.") -> DashboardView:
    return DashboardView(
        status="held_for_review",
        halted_at="drift_and_anomaly",
        output_before_checks=draft,
    )


class TestDashboardBrief:
    def test_the_brief_shows_the_draft_and_why_it_was_held(self) -> None:
        text = DashboardBrief().render(_held())
        assert "Use 'kick': I kick the ball." in text
        assert "held for your review" in text
        assert "drift and anomaly" in text
        assert "approve, edit, override or stop" in text

    def test_a_turn_awaiting_approval_names_no_gate(self) -> None:
        view = DashboardView(
            status="awaiting_tutor_approval", output_before_checks="Hi"
        )
        text = DashboardBrief().render(view)
        assert "passed every check" in text
        assert "stopped it" not in text

    def test_a_turn_without_a_draft_says_so(self) -> None:
        text = DashboardBrief().render(_held(None))
        assert "no draft" in text

    def test_the_card_describes_the_pupils_and_the_four_actions(self) -> None:
        card = DiligentTutorCard().system()
        assert "12 to 17" in card
        for word in ("approve", "edit", "override", "stop"):
            assert word in card


class TestDiligentTutor:
    def test_the_model_is_asked_with_the_card_and_the_dashboard(self) -> None:
        model = Prompts("override")
        decision = DiligentTutor(model, "card").decide(_held())
        assert decision == TutorDecision(decision="override")
        assert model.asked == [("card", DashboardBrief().render(_held()))]


class TestActionWord:
    @pytest.mark.parametrize(
        ("reply", "action"),
        [
            ("Approve.", "approve"),
            ("**override**", "override"),
            ("Stop! The pupil is at risk.", "stop"),
            ("edit\nThe draft needs a fix.", "edit"),
            ("  APPROVE", "approve"),
        ],
    )
    def test_the_first_word_counts_without_its_punctuation(
        self, reply: str, action: str
    ) -> None:
        assert ActionWord().parse(reply) == action

    @pytest.mark.parametrize("reply", ["approval", "I approve", "", "  ", "**"])
    def test_anything_else_is_not_an_action(self, reply: str) -> None:
        assert ActionWord().parse(reply) is None


class SeenViews(TutorRolePort):
    def __init__(self) -> None:
        self.views: list[DashboardView] = []

    def role(self) -> str:
        return "T1"

    def decide(self, view: DashboardView) -> TutorDecision:
        self.views.append(view)
        return TutorDecision(decision="none")


class TestTier1View:
    def test_a_held_turn_shows_the_role_the_gate_that_held_it(self) -> None:
        client = ScriptedTutor()
        client.status = "held_for_review"
        client.halted_at = "drift_and_anomaly"
        client.gate_decision = "pause"
        role = SeenViews()
        Tier1Runner(client, role).run(_case(), "hello", _LEARNER, "t")
        assert role.views[0].halted_at == "drift_and_anomaly"
