"""Pairwise negation of retrieved snippets (REQ-GATES)."""

from tutor_core.domain.models.retrieval import Snippet


class SnippetContradiction:
    """Two snippets contradict when one is the other's negation.

    Normalise by case-folding and collapsing whitespace. Text A negates
    text B when the normalised A equals ``not `` plus the normalised B,
    or the reverse. One snippet cannot contradict itself. The check is
    pairwise, in the order the result lists the snippets.
    """

    def found(self, snippets: tuple[Snippet, ...]) -> bool:
        """Return whether any pair is a negation."""
        texts = tuple(self._normal(snippet.content) for snippet in snippets)
        for index, left in enumerate(texts):
            for right in texts[index + 1 :]:
                if self._negates(left, right):
                    return True
        return False

    def _normal(self, text: str) -> str:
        return " ".join(text.casefold().split())

    def _negates(self, left: str, right: str) -> bool:
        return left == f"not {right}" or right == f"not {left}"
