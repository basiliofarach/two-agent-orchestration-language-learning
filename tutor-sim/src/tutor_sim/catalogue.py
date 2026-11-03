"""The sources a build may name. An excluded or rejected source is not admitted."""

import hashlib
import json
from pathlib import Path

from pydantic import TypeAdapter

from tutor_sim.domain.models.source import SourceRecord

_EXCLUDED = frozenset(
    {
        "write-and-improve-2024",
        "efcamdat",
        "ai4privacy",
        "english-vocabulary-profile",
        "clear-corpus",
        "standard-ebooks",
        "project-gutenberg",
        "simple-english-wikipedia",
        "onestopenglish",
        "author-grammar-notes",
    }
)


class SourceNotAdmitted(ValueError):
    """The build named a source DEC-0016 does not admit."""


class CatalogueDigest:
    """SHA-256 of a committed pin file.

    A later build replaces this with the digest of the fetched artefact.
    The pin file says which one ``sources.json`` currently records.
    """

    def of_file(self, path: Path) -> str:
        """Return the hex digest of the pin file's bytes."""
        return hashlib.sha256(path.read_bytes()).hexdigest()


class SourceCatalogue:
    """Load ``sources.json`` and refuse an excluded or rejected source."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> tuple[SourceRecord, ...]:
        """Return the admitted sources. A rejected review stops the build."""
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        records = TypeAdapter(tuple[SourceRecord, ...]).validate_python(payload)
        for record in records:
            if record.source_id in _EXCLUDED or record.licence_review == "rejected":
                msg = f"{record.source_id} is not admitted"
                raise SourceNotAdmitted(msg)
        return records
