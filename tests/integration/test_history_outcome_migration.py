"""b7e2c4a91d08 seals existing outcomes in place and grants columns, not tables."""

import base64
from uuid import UUID, uuid4

import psycopg
import pytest
from tests.support.migrated_database import MigratedDatabase
from tests.support.turn_app import KEK

from tutor_api.adapters.persistence.aes_gcm_envelope import AesGcmEnvelope
from tutor_api.adapters.persistence.learner_history import HistoryOutcomeCodec

_BEFORE = "7f3c2a91e0b4"
_LEARNER = UUID("00000000-0000-4000-8000-0000000000a1")


class LegacyHistory:
    """A database at the previous revision, holding boolean outcomes."""

    def __init__(self, url: str) -> None:
        self._url = url
        self.cipher = AesGcmEnvelope(key=KEK, key_id=UUID(int=1))

    def install(self, outcomes: tuple[bool, ...]) -> None:
        MigratedDatabase().upgrade(self._url, _BEFORE)
        with psycopg.connect(self._url) as connection:
            connection.execute(
                """
                INSERT INTO learner (learner_id, pseudonym, proficiency_level,
                                     retain_until)
                VALUES (%s, %s, %s, '2027-01-01T00:00:00Z')
                """,
                (_LEARNER, self.cipher.encrypt(b"p"), self.cipher.encrypt(b"A1")),
            )
            for index, correct in enumerate(outcomes):
                connection.execute(
                    """
                    INSERT INTO learner_history_event (
                        id, learner_id, item_id, correct, occurred_at
                    ) VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        uuid4(),
                        _LEARNER,
                        self.cipher.encrypt(b"item"),
                        correct,
                        f"2026-0{index + 1}-01T00:00:00Z",
                    ),
                )

    def column_type(self) -> str:
        with psycopg.connect(self._url) as connection:
            row = connection.execute(
                """
                SELECT udt_name FROM information_schema.columns
                WHERE table_name = 'learner_history_event' AND column_name = 'correct'
                """
            ).fetchone()
        assert row is not None
        return str(row[0])

    def values(self) -> list[object]:
        with psycopg.connect(self._url) as connection:
            rows = connection.execute(
                "SELECT correct FROM learner_history_event ORDER BY occurred_at"
            ).fetchall()
        return [row[0] for row in rows]


@pytest.fixture
def kek(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TUTOR_KEK", base64.b64encode(KEK).decode())
    monkeypatch.setenv("TUTOR_KEK_ID", str(UUID(int=1)))


class TestHistoryOutcomeMigration:
    def test_existing_boolean_outcomes_are_sealed_without_loss(
        self, fresh_database: str, kek: None
    ) -> None:
        legacy = LegacyHistory(fresh_database)
        legacy.install((True, False))
        assert legacy.column_type() == "bool"
        MigratedDatabase().upgrade(fresh_database)
        assert legacy.column_type() == "bytea"
        sealed = [bytes(value) for value in legacy.values()]  # type: ignore[arg-type]
        assert len(sealed[0]) == len(sealed[1])
        opened = [
            HistoryOutcomeCodec().decode(legacy.cipher.decrypt(value))
            for value in sealed
        ]
        assert opened == [True, False]

    def test_the_downgrade_restores_the_boolean_values(
        self, fresh_database: str, kek: None
    ) -> None:
        legacy = LegacyHistory(fresh_database)
        legacy.install((False, True))
        MigratedDatabase().upgrade(fresh_database)
        MigratedDatabase().downgrade(fresh_database, _BEFORE)
        assert legacy.column_type() == "bool"
        assert legacy.values() == [False, True]

    def test_an_empty_table_upgrades_and_downgrades_without_a_key(
        self, fresh_database: str
    ) -> None:
        MigratedDatabase().upgrade(fresh_database)
        legacy = LegacyHistory(fresh_database)
        assert legacy.column_type() == "bytea"
        MigratedDatabase().downgrade(fresh_database, _BEFORE)
        assert legacy.column_type() == "bool"
        MigratedDatabase().upgrade(fresh_database)
        assert legacy.column_type() == "bytea"
