"""Choose a dashboard action. The choice is a stimulus, never a score."""

from abc import ABC, abstractmethod

from tutor_sim.domain.models.tutor_role import DashboardView, TutorDecision


class TutorRolePort(ABC):
    """One tutor role. It sees only the dashboard view."""

    @abstractmethod
    def role(self) -> str:
        """``T1``, ``T2``, ``T3`` or ``T4``."""
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    def decide(self, view: DashboardView) -> TutorDecision:
        """The action for this held turn."""
        raise NotImplementedError  # pragma: no cover
