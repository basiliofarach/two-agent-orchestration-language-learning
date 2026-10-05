"""Deterministic local embeddings for the vetted corpus (DEC-0006)."""

import hashlib
import math

from tutor_core.domain.ports.embedding import EmbeddingPort


class LocalEmbedding(EmbeddingPort):
    """Map tokens into the pgvector width with a hashed bag of words.

    The same text always yields the same vector, so retrieval tests do not
    depend on a downloaded model. This port does not retrieve and does not
    call the language model. ``dimensions`` is the ``vector`` width the
    schema indexes; the composition root reads it from ``BaseSchema``.
    """

    def __init__(self, dimensions: int) -> None:
        self._dimensions = dimensions

    def embed(self, text: str) -> tuple[float, ...]:
        """Return one L2-normalised vector. Whitespace yields zeros."""
        weights = [0.0] * self._dimensions
        for token in text.casefold().split():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:2], "big") % self._dimensions
            sign = 1.0 - (2.0 * (digest[2] % 2))
            weights[index] += sign
        return self._normalise(weights)

    def _normalise(self, weights: list[float]) -> tuple[float, ...]:
        norm = math.sqrt(sum(item * item for item in weights))
        if norm == 0.0:
            return tuple(weights)
        return tuple(item / norm for item in weights)
