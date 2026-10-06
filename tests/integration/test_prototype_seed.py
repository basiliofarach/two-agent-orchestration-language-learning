"""The operator seed: idempotent, owner-only, and sealed at rest (DEC-0012)."""

import base64
from uuid import UUID

import psycopg
import pytest
from pydantic import SecretStr
from tests.support.migrated_database import MigratedDatabase
from tests.support.turn_app import KEK, THRESHOLD, TurnApp
from tests.support.turn_stubs import RecordingModel

from tutor_api.adapters.persistence.learner_history import HistoryOutcomeCodec
from tutor_api.curation.prototype_seed import PrototypePlan, SeedMain
from tutor_api.settings import ApplicationSettings
from tutor_core.domain.ports.cipher import CipherPort


class Counts:
    def of(self, url: str) -> tuple[int, ...]:
        with psycopg.connect(url) as connection:
            return tuple(
                int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])  # type: ignore[index]
                for table in (
                    "policy_version",
                    "kb_document",
                    "kb_chunk",
                    "learner",
                    "learner_history_event",
                    "tutoring_session",
                )
            )


class TestPrototypeSeed:
    async def test_the_seed_writes_once_and_a_rerun_changes_nothing(
        self, fresh_database: str
    ) -> None:
        app = TurnApp(fresh_database)
        container = app.container(RecordingModel())
        await app.install(container)
        first = Counts().of(fresh_database)
        assert first == (1, 1, 5, 1, 2, 1)
        await app.install(container)
        assert Counts().of(fresh_database) == first

    async def test_outcomes_are_sealed_one_byte_each(self, fresh_database: str) -> None:
        app = TurnApp(fresh_database)
        container = app.container(RecordingModel())
        await app.install(container)
        cipher = container.resolve(CipherPort)
        assert isinstance(cipher, CipherPort)
        with psycopg.connect(fresh_database) as connection:
            rows = connection.execute(
                "SELECT correct FROM learner_history_event ORDER BY id"
            ).fetchall()
        sealed = [bytes(row[0]) for row in rows]
        assert len(sealed[0]) == len(sealed[1])
        outcomes = [
            HistoryOutcomeCodec().decode(cipher.decrypt(value)) for value in sealed
        ]
        assert outcomes == [True, False]

    async def test_the_command_reads_settings_and_prints_the_identifiers(
        self, fresh_database: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        MigratedDatabase().upgrade(fresh_database)
        settings = ApplicationSettings(
            _env_file=None,  # type: ignore[call-arg]
            database_url=fresh_database,
            tutor_kek=SecretStr(base64.b64encode(KEK).decode()),
            tutor_kek_id=UUID(int=1),
            conflict_confidence_threshold=THRESHOLD,
        )
        assert await SeedMain().run(settings) == 0
        printed = capsys.readouterr().out
        plan = PrototypePlan().plan(THRESHOLD)
        assert f"session_id={plan.session_id}" in printed
        assert f"learner_id={plan.learner_id}" in printed

    async def test_the_command_refuses_without_a_threshold(self) -> None:
        settings = ApplicationSettings(_env_file=None)  # type: ignore[call-arg]
        with pytest.raises(ValueError, match="CONFLICT_CONFIDENCE_THRESHOLD"):
            await SeedMain().run(settings)
