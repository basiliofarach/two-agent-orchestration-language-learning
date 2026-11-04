"""The session's stored chain head, on Postgres with every migration applied.

The head is what turns a removed tail into a break (REQ-AUDIT). These tests
check that the insert trigger moves it, that the audit route and the
evidence survey both verify against it, that a stop racing a turn orders
the two instead of deadlocking, and that the revision backfills and
round-trips.
"""

import threading
import time
from collections.abc import Iterator
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from tests.integration.test_turn_router import Served
from tests.support.migrated_database import MigratedDatabase, PostgresUrl
from tests.support.turn_stubs import RecordingModel

from tutor_api.adapters.persistence.audit_query import (
    AuditRecordDecoder,
    PostgresAuditQuery,
)
from tutor_api.adapters.persistence.database import DatabaseEngine
from tutor_api.adapters.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tutor_api.evidence.survey import ChainSurvey, ChainSurveyResult
from tutor_core.domain.audit.chain import ChainVerifier

QUESTION = "What does hola mean in Spanish?"
_ENVELOPE = b"\x01" + bytes(44)
_HEAD_REVISION = "b7e2c4a91d05"
_BEFORE_HEAD = "c3a91e7b04d8"


@pytest.fixture
async def served(fresh_database: str) -> Served:
    served = Served(fresh_database, RecordingModel("Hola means hello in Spanish."))
    await served.install()
    return served


@pytest.fixture
def client(served: Served) -> Iterator[TestClient]:
    yield from served.client()


class Log:
    """Owner-side reads and the excision no application path can perform."""

    def __init__(self, served: Served) -> None:
        self._served = served

    def session_id(self) -> UUID:
        assert self._served.plan is not None
        return self._served.plan.session_id

    def head(self) -> str:
        rows = self._served.rows(
            "SELECT turn_chain_head FROM tutoring_session WHERE id = %s",
            self.session_id(),
        )
        return str(rows[0][0])

    def hashes(self) -> list[str]:
        rows = self._served.rows(
            "SELECT record_hash FROM turn_audit WHERE session_id = %s "
            "ORDER BY turn_index",
            self.session_id(),
        )
        return [str(row[0]) for row in rows]

    def excise(self, turn_ids: list[str]) -> None:
        """Delete turns as a superuser would, with every trigger switched off."""
        with psycopg.connect(self._served.url) as connection:
            connection.execute("SET session_replication_role = replica")
            for turn_id in turn_ids:
                for table in ("gate_evaluation", "turn_citation", "turn_audit"):
                    connection.execute(
                        f"DELETE FROM {table} WHERE turn_id = %s",  # noqa: S608
                        (UUID(turn_id),),
                    )

    async def survey(self) -> ChainSurveyResult:
        container = self._served.container
        decoder = container.resolve(AuditRecordDecoder)
        verifier = container.resolve(ChainVerifier)
        assert isinstance(decoder, AuditRecordDecoder)
        assert isinstance(verifier, ChainVerifier)
        engine = DatabaseEngine(PostgresUrl(self._served.url).async_url())
        result = ChainSurveyResult()
        try:
            connection = await engine.connect()
            await SqlAlchemyUnitOfWork(connection).run(
                ChainSurvey(PostgresAuditQuery(connection, decoder), verifier, result)
            )
        finally:
            await engine.dispose()
        return result


def _turn(served: Served, client: TestClient) -> dict[str, object]:
    response = client.post("/turns", json=served.body(QUESTION))
    assert response.status_code == 200, response.text
    return dict(response.json())


class TestStoredHead:
    async def test_each_turn_moves_the_head_to_its_digest(
        self, served: Served, client: TestClient
    ) -> None:
        log = Log(served)
        assert log.head() == "0" * 64
        _turn(served, client)
        _turn(served, client)
        assert log.head() == log.hashes()[-1]

    async def test_a_removed_tail_is_a_break_on_the_route_and_in_the_survey(
        self, served: Served, client: TestClient
    ) -> None:
        first = _turn(served, client)
        second = _turn(served, client)
        log = Log(served)
        log.excise([str(second["turn_id"])])
        audit = client.get(f"/sessions/{log.session_id()}/audit")
        assert audit.status_code == 200, audit.text
        view = audit.json()
        assert view["intact"] is False
        assert view["break_reason"] == "excised"
        assert view["break_turn_id"] == first["turn_id"]
        survey = await log.survey()
        assert survey.broken_sessions == (log.session_id(),)

    async def test_every_turn_removed_is_a_break_on_the_route_and_in_the_survey(
        self, served: Served, client: TestClient
    ) -> None:
        turn = _turn(served, client)
        log = Log(served)
        log.excise([str(turn["turn_id"])])
        view = client.get(f"/sessions/{log.session_id()}/audit").json()
        assert view["records"] == []
        assert view["intact"] is False
        assert view["break_reason"] == "excised"
        assert view["break_turn_id"] is None
        survey = await log.survey()
        assert survey.chain_status() == "broken"

    async def test_an_untouched_session_stays_intact(
        self, served: Served, client: TestClient
    ) -> None:
        _turn(served, client)
        log = Log(served)
        assert client.get(f"/sessions/{log.session_id()}/audit").json()["intact"]
        assert (await log.survey()).chain_status() == "intact"


class Insertion(threading.Thread):
    """One raw ``turn_audit`` insert on its own connection, run in a thread."""

    def __init__(self, url: str, session_id: UUID, policy_version: str) -> None:
        super().__init__(daemon=True)
        self._connection = psycopg.connect(url)
        self.pid = self._connection.info.backend_pid
        self._session_id = session_id
        self._policy_version = policy_version
        self.error: psycopg.Error | None = None

    def run(self) -> None:
        try:
            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO turn_audit (
                        turn_id, session_id, turn_index, learner_prompt_redacted,
                        redacted_categories, policy_version, previous_record_hash,
                        record_hash, recorded_at
                    ) VALUES (%s, %s, 0, %s, %s, %s, %s, %s, now())
                    """,
                    (
                        uuid4(),
                        self._session_id,
                        _ENVELOPE,
                        _ENVELOPE,
                        self._policy_version,
                        "0" * 64,
                        "a" * 64,
                    ),
                )
        except psycopg.Error as exc:
            self.error = exc
        finally:
            self._connection.close()


class TestStopRacingATurn:
    async def test_a_stop_holding_the_session_orders_the_turn_behind_it(
        self, served: Served
    ) -> None:
        """The stop path: share lock from the action guard, then a write.

        ``guard_human_action`` takes ``FOR SHARE`` on the session when the
        stop's action row is inserted, and ``mark_session_stopped`` then
        writes the row. A turn insert arriving between the two must wait
        for the stop and be refused, not deadlock against it.
        """
        log = Log(served)
        assert served.plan is not None
        with psycopg.connect(served.url) as stop:
            stop.execute(
                "SELECT 1 FROM tutoring_session WHERE id = %s FOR SHARE",
                (log.session_id(),),
            )
            turn = Insertion(served.url, log.session_id(), served.plan.policy_version)
            turn.start()
            self._wait_for_lock(served.url, turn.pid)
            stop.execute(
                "UPDATE tutoring_session SET stopped_at = now() WHERE id = %s",
                (log.session_id(),),
            )
        turn.join(timeout=10)
        assert not turn.is_alive()
        assert not isinstance(turn.error, psycopg.errors.DeadlockDetected)
        assert turn.error is not None
        assert "session is stopped" in str(turn.error)
        assert log.hashes() == []

    def _wait_for_lock(self, url: str, pid: int) -> None:
        with psycopg.connect(url, autocommit=True) as watcher:
            for _ in range(200):
                row = watcher.execute(
                    "SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s",
                    (pid,),
                ).fetchone()
                if row is not None and row[0] == "Lock":
                    return
                time.sleep(0.025)
        pytest.fail("the turn insert never waited on the session lock")


class TestChainHeadRevision:
    def test_the_backfill_takes_each_session_last_record(
        self, fresh_database: str
    ) -> None:
        database = MigratedDatabase()
        database.upgrade(fresh_database, _BEFORE_HEAD)
        database.seed_learner(fresh_database)
        with psycopg.connect(fresh_database) as connection:
            connection.execute(
                """
                INSERT INTO policy_version (
                    version, allowed_actions, denied_actions, escalation_rules,
                    article_mappings, effective_from
                ) VALUES ('v1', %s, %s, %s, %s, '2026-01-01T00:00:00Z')
                """,
                (_ENVELOPE, _ENVELOPE, _ENVELOPE, _ENVELOPE),
            )
            for index, digest in enumerate(("b", "c")):
                connection.execute(
                    """
                    INSERT INTO turn_audit (
                        turn_id, session_id, turn_index, learner_prompt_redacted,
                        redacted_categories, policy_version,
                        previous_record_hash, record_hash, recorded_at
                    ) VALUES (
                        %s, '00000000-0000-4000-8000-000000000004', %s, %s, %s,
                        'v1', 'a', %s, '2026-01-01T00:00:00Z'
                    )
                    """,
                    (uuid4(), index, _ENVELOPE, _ENVELOPE, digest),
                )
        database.upgrade(fresh_database, _HEAD_REVISION)
        with psycopg.connect(fresh_database) as connection:
            head = connection.execute(
                "SELECT turn_chain_head FROM tutoring_session"
            ).fetchone()
        assert head == ("c",)

    def test_the_revision_downgrades_and_upgrades_again(
        self, fresh_database: str
    ) -> None:
        database = MigratedDatabase()
        database.upgrade(fresh_database)
        database.downgrade(fresh_database, _BEFORE_HEAD)
        with psycopg.connect(fresh_database) as connection:
            columns = connection.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'tutoring_session'
                  AND column_name = 'turn_chain_head'
                """
            ).fetchall()
            exemption = connection.execute(
                "SELECT count(*) FROM protected_column_exemption "
                "WHERE column_name = 'turn_chain_head'"
            ).fetchone()
        assert columns == []
        assert exemption == (0,)
        database.upgrade(fresh_database)
        with psycopg.connect(fresh_database) as connection:
            exemption = connection.execute(
                "SELECT decision_ref FROM protected_column_exemption "
                "WHERE column_name = 'turn_chain_head'"
            ).fetchone()
        assert exemption == ("DEC-0012",)
