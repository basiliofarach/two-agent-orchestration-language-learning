"""Grammar findings on a draft. The check does not rewrite it."""

from abc import ABC, abstractmethod

from tutor_core.domain.models.safety import GrammarFinding


class GrammarCheckPort(ABC):
    """Report grammar findings on a draft (REQ-COMP).

    Scope boundary: findings only. This port does not rewrite or drop text.
    """

    @abstractmethod
    def check(self, text: str) -> tuple[GrammarFinding, ...]:
        """Return grammar findings for ``text``."""
        raise NotImplementedError  # pragma: no cover
