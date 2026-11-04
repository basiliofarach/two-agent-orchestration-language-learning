"""T1 asks the role model. T2, T3 and T4 are scripts. None of them score."""

from tutor_sim.domain.models.tutor_role import DashboardView, TutorDecision
from tutor_sim.domain.ports.role_model import RoleModelPort
from tutor_sim.domain.ports.tutor_role import TutorRolePort

_ACTIONS = frozenset({"approve", "edit", "override", "stop"})


class ActionWord:
    """The first word of a role-model reply, when it is a dashboard action."""

    def parse(self, text: str) -> str | None:
        """``None`` when the reply is blank or not an action."""
        stripped = text.strip().lower()
        if not stripped:
            return None
        token = stripped.split(" ", 1)[0]
        if token not in _ACTIONS:
            return None
        return token


class DiligentTutor(TutorRolePort):
    """T1. Unparseable output becomes ``none`` and is a role failure."""

    def __init__(self, model: RoleModelPort, prompt: str) -> None:
        self._model = model
        self._prompt = prompt
        self._words = ActionWord()

    def role(self) -> str:
        """T1."""
        return "T1"

    def decide(self, view: DashboardView) -> TutorDecision:
        """Ask the model. An edit uses the draft the dashboard showed."""
        action = self._words.parse(self._model.complete(self._prompt, view.status))
        if action is None:
            return TutorDecision(decision="none", role_failure=True)
        if action == "edit":
            draft = view.output_before_checks
            if draft is None or not draft.strip():
                return TutorDecision(decision="none", role_failure=True)
            return TutorDecision(
                decision="edit", edited_output=draft, role_failure=False
            )
        if action == "approve":
            return TutorDecision(decision="approve")
        if action == "override":
            return TutorDecision(decision="override")
        return TutorDecision(decision="stop")


class ComplacentTutor(TutorRolePort):
    """T2. Approve a release. On hold, edit the draft through unchanged."""

    def role(self) -> str:
        """T2."""
        return "T2"

    def decide(self, view: DashboardView) -> TutorDecision:
        """No draft on a hold means the role does nothing."""
        if view.status == "awaiting_tutor_approval":
            return TutorDecision(decision="approve")
        draft = view.output_before_checks
        if draft is None:
            return TutorDecision(decision="none")
        return TutorDecision(decision="edit", edited_output=draft)


class AbsentTutor(TutorRolePort):
    """T3. The turn is never actioned."""

    def role(self) -> str:
        """T3."""
        return "T3"

    def decide(self, view: DashboardView) -> TutorDecision:
        """Always ``none``. The view is seen and not used."""
        del view
        return TutorDecision(decision="none")


class StoppingTutor(TutorRolePort):
    """T4. Stop at the planned turn. Otherwise release or override."""

    def __init__(self, stop_at_turn: int) -> None:
        self._stop_at = stop_at_turn

    def role(self) -> str:
        """T4."""
        return "T4"

    def decide(self, view: DashboardView) -> TutorDecision:
        """Stop wins over approve and override."""
        if view.turn_index == self._stop_at:
            return TutorDecision(decision="stop")
        if view.status == "awaiting_tutor_approval":
            return TutorDecision(decision="approve")
        return TutorDecision(decision="override")


class UnknownTutorRole(Exception):
    """An episode names a tutor role the harness was not given."""


class TutorRoster:
    """The tutor roles one command may use, looked up by their own name.

    The roles are built in the composition root. An episode chooses one by
    ``EpisodeSpec.tutor_role``; it never constructs one.
    """

    def __init__(self, roles: tuple[TutorRolePort, ...]) -> None:
        self._roles = {role.role(): role for role in roles}
        if len(self._roles) != len(roles):
            msg = "two tutor roles share a name"
            raise ValueError(msg)

    def role(self, name: str) -> TutorRolePort:
        """The role registered under ``name``."""
        try:
            return self._roles[name]
        except KeyError as exc:
            msg = f"no tutor role {name}"
            raise UnknownTutorRole(msg) from exc
