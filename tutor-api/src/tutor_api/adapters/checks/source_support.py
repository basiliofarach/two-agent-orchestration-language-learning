"""Flag unsupported spans. Do not remove them (REQ-ACCURACY)."""

from tutor_core.domain.models.retrieval import Snippet
from tutor_core.domain.models.safety import ClaimSpan, SourceSupportReport
from tutor_core.domain.ports.source_support import SourceSupportPort


class SentenceSplitter:
    """Split a draft on sentence marks, keeping each sentence's offsets."""

    _MARKS = ".!?"

    def split(self, draft: str) -> tuple[tuple[str, int, int], ...]:
        """Return ``(text, start, end)`` for each non-blank sentence."""
        found: list[tuple[str, int, int]] = []
        start = 0
        for index, character in enumerate(draft):
            if character not in self._MARKS:
                continue
            found.extend(self._piece(draft, start, index + 1))
            start = index + 1
        found.extend(self._piece(draft, start, len(draft)))
        return tuple(found)

    def _piece(
        self, draft: str, start: int, end: int
    ) -> tuple[tuple[str, int, int], ...]:
        chunk = draft[start:end]
        text = chunk.strip()
        if not text:
            return ()
        leading = len(chunk) - len(chunk.lstrip())
        span_start = start + leading
        return ((text, span_start, span_start + len(text)),)


class OverlapSourceSupport(SourceSupportPort):
    """A sentence is supported when its text overlaps a retrieved passage.

    Normalise by case-folding and collapsing whitespace. A sentence of
    fewer than two words is not treated as a claim: it is listed as
    unsupported, so a short fragment is not marked supported by accident.
    The draft is not edited. Unsupported spans stay on the report.
    ``source_ids`` on a supported span are the source URIs that overlapped.
    """

    def __init__(self, sentences: SentenceSplitter) -> None:
        self._sentences = sentences

    def verify(
        self,
        draft: str,
        snippets: tuple[Snippet, ...],
    ) -> SourceSupportReport:
        """Return supported and unsupported spans. Neither list drops the other."""
        supported: list[ClaimSpan] = []
        unsupported: list[ClaimSpan] = []
        for text, start, end in self._sentences.split(draft):
            matched = self._matching(text, snippets)
            span = ClaimSpan(
                text=text,
                start=start,
                end=end,
                source_ids=matched,
            )
            if matched:
                supported.append(span)
            else:
                unsupported.append(span)
        total = len(supported) + len(unsupported)
        ratio = 1.0 if total == 0 else len(supported) / total
        return SourceSupportReport(
            supported=tuple(supported),
            unsupported=tuple(unsupported),
            support_ratio=ratio,
        )

    def _matching(
        self, sentence: str, snippets: tuple[Snippet, ...]
    ) -> tuple[str, ...]:
        normalised = self._normal(sentence)
        if len(normalised.split()) < 2:
            return ()
        found: list[str] = []
        for snippet in snippets:
            material = self._normal(snippet.content)
            uri = snippet.source.source_uri
            if uri not in found and (normalised in material or material in normalised):
                found.append(uri)
        return tuple(found)

    def _normal(self, text: str) -> str:
        return " ".join(text.casefold().split())
