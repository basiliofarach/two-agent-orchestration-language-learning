"""Flag unsafe or out-of-scope content. Flags are not gate verdicts."""

from abc import ABC, abstractmethod

from tutor_core.domain.models.safety import SafetyFlag


class SafetyClassifierPort(ABC):
    """Flag unsafe or out-of-scope content (REQ-COMP).

    Scope boundary: classification only. Flags are facts about the draft.
    This port does not decide a gate verdict and does not remove text.
    """

    @abstractmethod
    def classify(self, text: str) -> tuple[SafetyFlag, ...]:
        """Return safety flags for ``text``."""
        raise NotImplementedError  # pragma: no cover
