"""Persona-conditioned completion. The harness holds no tutor-API client."""

from abc import ABC, abstractmethod


class RoleModelPort(ABC):
    """One completion. The digest is the weights, never a tag."""

    @abstractmethod
    def weights_sha(self) -> str:
        """The pinned weights digest this completion was drawn from."""
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    def complete(self, system: str, user: str) -> str:
        """Return the utterance. ``system`` is the persona card."""
        raise NotImplementedError  # pragma: no cover
