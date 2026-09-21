"""Redact PII before any agent or the audit log sees learner text."""

from abc import ABC, abstractmethod

from tutor_core.domain.models.safety import RedactedText


class PiiRedactionPort(ABC):
    """Redact PII from learner input in real time (REQ-MINOR).

    Scope boundary: this port runs at the input boundary. Nothing downstream
    of it — agents, gates, or the audit log — receives raw learner text.
    """

    @abstractmethod
    def redact(self, text: str) -> RedactedText:
        """Return the redacted text and the categories removed."""
        raise NotImplementedError  # pragma: no cover
