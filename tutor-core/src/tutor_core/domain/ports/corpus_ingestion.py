"""Ingest curated material. Retrieval is a different port."""

from abc import ABC, abstractmethod

from tutor_core.domain.models.corpus import CorpusDocument, IngestedDocument


class CorpusIngestionPort(ABC):
    """Record source, version, and review status for one document (REQ-KB).

    Scope boundary: curation only. This port does not retrieve, and it
    exposes no open-web or URL-fetch method. A document with no review
    status is refused; nothing is defaulted to reviewed. Re-ingesting a
    source at a new version inserts a new row. Async because it writes on
    an enlisted connection (DEC-0014).
    """

    @abstractmethod
    async def ingest(self, document: CorpusDocument) -> IngestedDocument:
        """Insert the document and its chunks. Never update an existing row."""
        raise NotImplementedError  # pragma: no cover
