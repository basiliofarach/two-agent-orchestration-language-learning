"""Provenance is sealed, and a missing triple is unlevelled."""

import pytest
from pydantic import ValidationError
from tests.support.reversible_cipher import ReversibleCipher

from tutor_api.adapters.persistence.provenance import DocumentProvenance, ProvenanceRead
from tutor_api.adapters.persistence.schema import KbDocumentProvenance


class TestProvenanceStatements:
    def test_the_upgrade_adds_ciphertext_columns_together(self) -> None:
        sql = " ".join(KbDocumentProvenance().statements())
        assert "ADD COLUMN licence ciphertext" in sql
        assert "ADD COLUMN cefr_level ciphertext" in sql
        assert "ADD COLUMN level_method ciphertext" in sql
        assert "kb_document_provenance_together" in sql

    def test_the_downgrade_drops_the_check_before_the_columns(self) -> None:
        sql = " ".join(KbDocumentProvenance().downgrade_statements())
        assert sql.index("DROP CONSTRAINT") < sql.index("DROP COLUMN licence")


class TestProvenanceRead:
    def test_a_null_triple_is_unlevelled(self) -> None:
        reading = ProvenanceRead(ReversibleCipher()).read(None, None, None)
        assert reading.unlevelled is True
        assert reading.licence is None

    def test_a_sealed_triple_opens(self) -> None:
        cipher = ReversibleCipher()
        reading = ProvenanceRead(cipher).read(
            cipher.encrypt(b"author-own"),
            cipher.encrypt(b"A1"),
            cipher.encrypt(b"author-assigned"),
        )
        assert reading == DocumentProvenance(
            unlevelled=False,
            licence="author-own",
            cefr_level="A1",
            level_method="author-assigned",
        )

    @pytest.mark.parametrize(
        "columns",
        [
            (b"sealed:x", None, None),
            (None, b"sealed:A1", b"sealed:author-assigned"),
            (b"sealed:x", None, b"sealed:method"),
            (b"sealed:x", b"sealed:A1", None),
            (None, None, b"sealed:method"),
        ],
    )
    def test_a_partial_triple_is_refused(
        self, columns: tuple[bytes | None, bytes | None, bytes | None]
    ) -> None:
        with pytest.raises(ValueError, match="together"):
            ProvenanceRead(ReversibleCipher()).read(*columns)

    def test_the_reading_rejects_an_undeclared_field(self) -> None:
        reading = DocumentProvenance(unlevelled=True)
        with pytest.raises(ValidationError):
            DocumentProvenance.model_validate({**reading.model_dump(), "nope": 1})
        with pytest.raises(ValidationError):
            reading.unlevelled = False
