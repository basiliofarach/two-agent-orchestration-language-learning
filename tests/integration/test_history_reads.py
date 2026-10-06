"""History reads on Postgres. Retention and the requested fields are in the SQL."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import psycopg
from tests.support.migrated_database import MigratedDatabase, PostgresUrl

from tutor_api.adapters.frozen_clock import FrozenClock
from tutor_api.adapters.persistence.aes_gcm_envelope import AesGcmEnvelope
from tutor_api.adapters.persistence.database import DatabaseEngine, RequestConnection
from tutor_api.adapters.persistence.learner_history import (
    HistoryOutcomeCodec,
    PostgresLearnerHistory,
)
from tutor_core.domain.models.learner import HistoryFieldSet, LearnerId
from tutor_core.domain.ports.unit_of_work import TransactionConnection

_WHEN = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
_FUTURE = datetime(2026, 12, 1, tzinfo=UTC)
_PAST = datetime(2020, 1, 1, tzinfo=UTC)
_OCCURRED = datetime(2026, 6, 1, tzinfo=UTC)


class TracingConnection(TransactionConnection):
    """The real connection, with every statement kept for the assertion."""

    def __init__(self, inner: TransactionConnection) -> None:
        self._inner = inner
        self.statements: list[str] = []

    async def commit(self) -> None:
        await self._inner.commit()

    async def rollback(self) -> None:
        await self._inner.rollback()

    async def close(self) -> None:
        await self._inner.close()

    async def execute(
        self, statement: str, parameters: dict[str, object] | None = None
    ) -> None:
        self.statements.append(statement)
        await self._inner.execute(statement, parameters)

    async def fetch_one(
        self, statement: str, parameters: dict[str, object]
    ) -> tuple[object, ...] | None:
        self.statements.append(statement)
        return await self._inner.fetch_one(statement, parameters)

    async def fetch_all(
        self, statement: str, parameters: dict[str, object]
    ) -> tuple[tuple[object, ...], ...]:
        self.statements.append(statement)
        return await self._inner.fetch_all(statement, parameters)


class HistoryDatabase:
    """One migrated database and a history adapter over its connection."""

    def __init__(self, url: str) -> None:
        MigratedDatabase().upgrade(url)
        self._url = url
        self.cipher = AesGcmEnvelope(key=bytes(range(32)), key_id=UUID(int=1))
        self.engine = DatabaseEngine(PostgresUrl(url).async_url())
        self.connection = TracingConnection(RequestConnection(self.engine))

    def reader(self) -> PostgresLearnerHistory:
        return PostgresLearnerHistory(
            self.connection,
            self.cipher,
            FrozenClock(_WHEN),
            HistoryFieldSet(fields=("proficiency_level", "events")),
            HistoryOutcomeCodec(),
        )

    def fields(self, *names: str) -> HistoryFieldSet:
        return HistoryFieldSet.model_validate({"fields": names})

    def insert(
        self,
        learner_id: UUID,
        proficiency: str,
        retain_until: datetime,
        item_id: str | None,
    ) -> None:
        with psycopg.connect(self._url) as connection:
            connection.execute(
                """
                INSERT INTO learner (
                    learner_id, pseudonym, proficiency_level, retain_until
                ) VALUES (%s, %s, %s, %s)
                """,
                (
                    learner_id,
                    self.cipher.encrypt(b"learner"),
                    self.cipher.encrypt(proficiency.encode("utf-8")),
                    retain_until,
                ),
            )
            if item_id is None:
                return
            connection.execute(
                """
                INSERT INTO learner_history_event (
                    id, learner_id, item_id, correct, occurred_at
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    uuid4(),
                    learner_id,
                    self.cipher.encrypt(item_id.encode("utf-8")),
                    self.cipher.encrypt(HistoryOutcomeCodec().encode(True)),
                    _OCCURRED,
                ),
            )

    def events(self, learner_id: UUID, rows: tuple[tuple[UUID, str], ...]) -> None:
        """Insert events that share one instant, in the order given."""
        with psycopg.connect(self._url) as connection:
            for event_id, item_id in rows:
                connection.execute(
                    """
                    INSERT INTO learner_history_event (
                        id, learner_id, item_id, correct, occurred_at
                    ) VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        event_id,
                        learner_id,
                        self.cipher.encrypt(item_id.encode("utf-8")),
                        self.cipher.encrypt(HistoryOutcomeCodec().encode(True)),
                        _OCCURRED,
                    ),
                )

    async def close(self) -> None:
        await self.connection.close()
        await self.engine.dispose()


class TestLearnerHistory:
    async def test_the_generated_sql_selects_only_requested_columns(
        self, fresh_database: str
    ) -> None:
        database = HistoryDatabase(fresh_database)
        learner = uuid4()
        database.insert(learner, "A2", _FUTURE, "greet-1")
        try:
            snapshot = await database.reader().read(
                LearnerId(value=learner), database.fields("proficiency_level")
            )
        finally:
            await database.close()
        assert snapshot.proficiency_level == "A2"
        assert snapshot.events is None
        joined = " ".join(database.connection.statements)
        assert "proficiency_level" in joined
        assert "learner_history_event" not in joined
        assert "pseudonym" not in joined

    async def test_expired_retain_until_yields_no_history(
        self, fresh_database: str
    ) -> None:
        database = HistoryDatabase(fresh_database)
        learner = uuid4()
        database.insert(learner, "A2", _PAST, "greet-1")
        try:
            snapshot = await database.reader().read(
                LearnerId(value=learner),
                database.fields("proficiency_level", "events"),
            )
        finally:
            await database.close()
        assert snapshot.proficiency_level is None
        assert snapshot.events is None
        joined = " ".join(database.connection.statements)
        assert "learner_history_event" not in joined
        assert "proficiency_level" not in joined

    async def test_an_admitted_event_round_trips(self, fresh_database: str) -> None:
        database = HistoryDatabase(fresh_database)
        learner = uuid4()
        database.insert(learner, "A2", _FUTURE, "greet-1")
        try:
            snapshot = await database.reader().read(
                LearnerId(value=learner), database.fields("events")
            )
        finally:
            await database.close()
        assert snapshot.events is not None
        assert snapshot.events[0].item_id == "greet-1"
        assert snapshot.events[0].correct is True
        assert snapshot.proficiency_level is None

    async def test_events_that_share_a_timestamp_are_ordered_by_id(
        self, fresh_database: str
    ) -> None:
        database = HistoryDatabase(fresh_database)
        learner = uuid4()
        database.insert(learner, "A2", _FUTURE, None)
        later = UUID("00000000-0000-4000-8000-000000000002")
        earlier = UUID("00000000-0000-4000-8000-000000000001")
        database.events(
            learner,
            ((later, "second"), (earlier, "first")),
        )
        try:
            snapshot = await database.reader().read(
                LearnerId(value=learner), database.fields("events")
            )
        finally:
            await database.close()
        assert snapshot.events is not None
        assert [event.item_id for event in snapshot.events] == ["first", "second"]
