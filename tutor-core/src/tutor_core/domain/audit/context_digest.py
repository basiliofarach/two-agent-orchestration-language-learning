"""Digest of the cited context a turn was generated from (REQ-AUDIT, REQ-KB)."""

import hashlib
import json

from tutor_core.domain.models.retrieval import Snippet


class CitedContextDigest:
    """SHA-256 of the cited snippets, in the order the template rendered them.

    The record stores chunk ids, and the chunk text lives in the corpus,
    which can be re-ingested or retracted after the turn. Without this
    digest a replay would render whatever the corpus holds today and could
    not tell that it differs. Every snippet field is covered: the text, the
    source, its version and its review status, all of which the template
    renders.
    """

    def digest(self, snippets: tuple[Snippet, ...]) -> str:
        """Return the hex digest of the canonical snippet sequence."""
        payload = json.dumps(
            [snippet.model_dump(mode="json") for snippet in snippets],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
