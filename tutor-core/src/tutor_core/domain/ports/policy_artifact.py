"""Read the versioned policy. The port does not author rules."""

from abc import ABC, abstractmethod

from tutor_core.domain.policy.policy_card import PolicyCard


class PolicyArtifactPort(ABC):
    """Supply the versioned machine-readable policy (REQ-POLICY).

    Scope boundary: read-only. ``current()`` and ``version()`` only. The
    version string is what lands in the audit record and on each gate
    verdict, so the log records which rule version was checked.
    """

    @abstractmethod
    def current(self) -> PolicyCard:
        """Return the policy card in force."""
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    def version(self) -> str:
        """Return the policy version string written into the audit record."""
        raise NotImplementedError  # pragma: no cover
