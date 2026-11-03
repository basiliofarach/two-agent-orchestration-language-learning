"""Compare an artefact with the digest recorded on its source."""

import hashlib

from tutor_sim.domain.models.source import SourceRecord


class DigestMismatch(ValueError):
    """The fetched bytes are not the pinned artefact."""


class ArtefactDigest:
    """SHA-256 of the bytes a fetch returned."""

    def check(self, source: SourceRecord, body: bytes) -> None:
        """Raise when the body is not the recorded digest."""
        actual = hashlib.sha256(body).hexdigest()
        if actual != source.sha256:
            msg = f"{source.source_id} digest mismatch"
            raise DigestMismatch(msg)
