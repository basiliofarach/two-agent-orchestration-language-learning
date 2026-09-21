"""Map text to a vector. No retrieval and no generation."""

from abc import ABC, abstractmethod


class EmbeddingPort(ABC):
    """Map text to a vector.

    Scope boundary: embedding only. This port carries no REQ-* of its own
    (DEC-0001). It does not retrieve, generate, or reach the network.
    """

    @abstractmethod
    def embed(self, text: str) -> tuple[float, ...]:
        """Return one embedding vector for ``text``."""
        raise NotImplementedError  # pragma: no cover
