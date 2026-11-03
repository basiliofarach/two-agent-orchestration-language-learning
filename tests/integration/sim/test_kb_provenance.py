"""The provenance columns survive an upgrade, and a partial row does not."""

from pathlib import Path
from uuid import UUID

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from tests.support.reversible_cipher import ReversibleCipher

from tutor_api.adapters.persistence.aes_gcm_envelope import AesGcmEnvelope
from tutor_api.adapters.persistence.provenance import ProvenanceRead

_LEGACY = UUID("00000000-0000-4000-8000-000000000091")
_FULL = UUID("00000000-0000-4000-8000-000000000092")
_COLUMNS = ("licence", "cefr_level", "level_method")


class AlembicAt:
    def __init__(self, url: str) -> None:
        root = Path(__file__).resolve().parents[3] / "tutor-api"
        self._config = Config(str(root / "alembic.ini"))
        self._config.set_main_option("script_location", str(root / "alembic"))
        self._config.set_main_option("sqlalchemy.url", self._sync(url))

    def upgrade(self) -> None:
        command.upgrade(self._config, "head")

    def downgrade_to(self, revision: str) -> None:
        command.downgrade(self._config, revision)

    def _sync(self, url: str) -> str:
        return url.replace("postgresql://", "postgresql+psycopg://", 1)


class ProvenanceColumns:
    def names(
        self, connection: psycopg.Connection[tuple[object, ...]]
    ) -> dict[str, str]:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name, domain_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'kb_document'
                  AND column_name = ANY(%s)
                """,
                (list(_COLUMNS),),
            )
            return {str(name): str(domain) for name, domain in cursor.fetchall()}


class TestKbDocumentProvenance:
    def test_columns_round_trip_and_a_legacy_row_is_unlevelled(
        self, fresh_database: str
    ) -> None:
        alembic = AlembicAt(fresh_database)
        alembic.upgrade()
        with psycopg.connect(fresh_database) as connection:
            assert ProvenanceColumns().names(connection) == {
                name: "ciphertext" for name in _COLUMNS
            }
            self._insert_legacy(connection)
            self._reject_partial(connection)
            self._insert_full(connection)
            self._assert_unlevelled(connection)
            self._assert_no_exemption(connection)
        alembic.downgrade_to("5e1f0c7a9b23")
        with psycopg.connect(fresh_database) as connection:
            assert ProvenanceColumns().names(connection) == {}
        alembic.upgrade()
        with psycopg.connect(fresh_database) as connection:
            assert set(ProvenanceColumns().names(connection)) == set(_COLUMNS)

    def _insert_legacy(
        self, connection: psycopg.Connection[tuple[object, ...]]
    ) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO kb_document (id, source_uri, version, review_status)
                VALUES (%s, 'kb://legacy', '1', 'approved')
                """,
                (_LEGACY,),
            )
        connection.commit()

    def _reject_partial(
        self, connection: psycopg.Connection[tuple[object, ...]]
    ) -> None:
        envelope = AesGcmEnvelope(key=bytes(range(32)), key_id=UUID(int=1)).encrypt(
            b"only"
        )
        with connection.cursor() as cursor, pytest.raises(psycopg.Error):
            cursor.execute(
                """
                INSERT INTO kb_document (
                    id, source_uri, version, review_status, licence
                )
                VALUES (%s, 'kb://partial', '1', 'approved', %s)
                """,
                (UUID("00000000-0000-4000-8000-000000000093"), envelope),
            )
        connection.rollback()

    def _insert_full(self, connection: psycopg.Connection[tuple[object, ...]]) -> None:
        cipher = AesGcmEnvelope(key=bytes(range(32)), key_id=UUID(int=1))
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO kb_document (
                    id, source_uri, version, review_status,
                    licence, cefr_level, level_method
                )
                VALUES (%s, 'kb://full', '1', 'approved', %s, %s, %s)
                """,
                (
                    _FULL,
                    cipher.encrypt(b"author-own"),
                    cipher.encrypt(b"A1"),
                    cipher.encrypt(b"author-assigned"),
                ),
            )
            cursor.execute(
                """
                SELECT licence, cefr_level, level_method
                FROM kb_document WHERE id = %s
                """,
                (_FULL,),
            )
            row = cursor.fetchone()
        assert row is not None
        reading = ProvenanceRead(cipher).read(row[0], row[1], row[2])
        assert reading.unlevelled is False
        assert reading.licence == "author-own"
        connection.commit()

    def _assert_unlevelled(
        self, connection: psycopg.Connection[tuple[object, ...]]
    ) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT licence, cefr_level, level_method
                FROM kb_document WHERE id = %s
                """,
                (_LEGACY,),
            )
            row = cursor.fetchone()
        assert row == (None, None, None)
        reading = ProvenanceRead(ReversibleCipher()).read(None, None, None)
        assert reading.unlevelled is True

    def _assert_no_exemption(
        self, connection: psycopg.Connection[tuple[object, ...]]
    ) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name
                FROM protected_column_exemption
                WHERE table_name = 'kb_document'
                  AND column_name = ANY(%s)
                """,
                (list(_COLUMNS),),
            )
            assert cursor.fetchall() == []
