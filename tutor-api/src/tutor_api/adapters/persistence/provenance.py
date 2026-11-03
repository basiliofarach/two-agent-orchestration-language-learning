"""Read the three provenance columns. Absence is unlevelled, not a backfill."""

from pydantic import BaseModel, ConfigDict

from tutor_core.domain.ports.cipher import CipherPort


class DocumentProvenance(BaseModel):
    """The licence and level on one document, or the fact that it has neither."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    unlevelled: bool
    licence: str | None = None
    cefr_level: str | None = None
    level_method: str | None = None


class ProvenanceRead:
    """Open a ciphertext triple. The database does not decrypt it."""

    def __init__(self, cipher: CipherPort) -> None:
        self._cipher = cipher

    def read(
        self,
        licence: bytes | None,
        cefr_level: bytes | None,
        level_method: bytes | None,
    ) -> DocumentProvenance:
        """All three absent is unlevelled. A partial triple is refused."""
        if licence is None and cefr_level is None and level_method is None:
            return DocumentProvenance(unlevelled=True)
        if licence is None or cefr_level is None or level_method is None:
            msg = "provenance columns are set together"
            raise ValueError(msg)
        return DocumentProvenance(
            unlevelled=False,
            licence=self._open(licence),
            cefr_level=self._open(cefr_level),
            level_method=self._open(level_method),
        )

    def _open(self, envelope: bytes) -> str:
        return self._cipher.decrypt(envelope).decode("utf-8")
