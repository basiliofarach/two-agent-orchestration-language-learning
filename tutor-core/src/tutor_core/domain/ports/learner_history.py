"""Read the minimal student-history fields."""

from abc import ABC, abstractmethod

from tutor_core.domain.models.learner import (
    HistoryFieldSet,
    LearnerHistorySnapshot,
    LearnerId,
)


class LearnerHistoryPort(ABC):
    """Read minimal student-history fields (REQ-HISTORY).

    Scope boundary: read-only. The field allowlist is a constructor argument
    of the implementation; only those fields are admitted. This port has no
    write method.
    """

    @abstractmethod
    async def read(
        self,
        learner_id: LearnerId,
        requested: HistoryFieldSet,
    ) -> LearnerHistorySnapshot:
        """Return the requested history fields for one learner.

        Only ``requested`` is selected, and ``requested`` must sit inside the
        allowlist: a field outside it raises rather than being read or
        silently dropped (REQ-HISTORY). Async because the read runs on the
        turn's enlisted connection (DEC-0014).
        """
        raise NotImplementedError  # pragma: no cover
