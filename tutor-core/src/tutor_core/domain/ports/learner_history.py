"""Read the minimal student-history fields."""

from abc import ABC, abstractmethod

from tutor_core.domain.models.learner import LearnerHistorySnapshot, LearnerId


class LearnerHistoryPort(ABC):
    """Read minimal student-history fields (REQ-HISTORY).

    Scope boundary: read-only. The field allowlist is a constructor argument
    of the implementation; only those fields are admitted. This port has no
    write method.
    """

    @abstractmethod
    def read(self, learner_id: LearnerId) -> LearnerHistorySnapshot:
        """Return the allowlisted history for one learner."""
        raise NotImplementedError  # pragma: no cover
