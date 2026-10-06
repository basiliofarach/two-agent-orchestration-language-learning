"""Dashboard persistence adapters on a scripted connection (rule 7)."""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from tests.support.dashboard_stubs import SESSION_ID, MemoryAuditQuery, SealedRecords
from tests.support.reversible_cipher import ReversibleCipher
from tests.support.samples import Samples
from tests.support.scripted_connection import ScriptedConnection

from tutor_api.adapters.frozen_clock import FrozenClock
from tutor_api.adapters.persistence.audit_query import (
    AuditRecordDecoder,
    PostgresAuditQuery,
)
from tutor_api.adapters.persistence.base import BaseRepository, RowReader
from tutor_api.adapters.persistence.cohort_report import PostgresCohortReport
from tutor_api.adapters.persistence.human_action import PostgresHumanAction
from tutor_api.adapters.persistence.sealed import SealedValue
from tutor_api.adapters.persistence.session_directory import PostgresSessionDirectory
from tutor_api.evidence.survey import ChainSurvey, ChainSurveyResult
from tutor_api.retention.purge import PurgeLog, RetentionPurge
from tutor_core.domain.audit.chain import ChainVerifier
from tutor_core.domain.audit.record_hash import ActionRecordHash, AuditRecordHash
from tutor_core.domain.models.audit import GATE_ORDER, HumanAction
from tutor_core.domain.models.session import SessionOpening
from tutor_core.domain.ports.audit_query import AuditRecordUnreadable
from tutor_core.domain.ports.human_action import ActionRejected
from tutor_core.domain.ports.session_directory import SessionOpenRejected

WHEN = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


class DriverError(Exception):
    """What psycopg raises: ``sqlstate`` and ``diag.message_primary``."""

    class Diag:
        def __init__(self, message: str) -> None:
            self.message_primary = message

    def __init__(self, sqlstate: str, message: str) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate
        self.diag = self.Diag(message)


class RefusingConnection(ScriptedConnection):
    """Raise ``error`` on the first statement containing ``marker``."""

    def __init__(
        self,
        marker: str,
        error: Exception,
        rows: tuple[tuple[object, ...], ...] = (),
    ) -> None:
        super().__init__(rows)
        self._marker = marker
        self._error = error

    async def execute(
        self, statement: str, parameters: Mapping[str, object] | None = None
    ) -> None:
        self._refuse(statement)
        await super().execute(statement, parameters)

    async def fetch_one(
        self, statement: str, parameters: Mapping[str, object]
    ) -> tuple[object, ...] | None:
        self._refuse(statement)
        return await super().fetch_one(statement, parameters)

    def _refuse(self, statement: str) -> None:
        if self._marker in statement:
            raise self._error


class KeyedConnection(ScriptedConnection):
    """Answer each statement with the rows of the first marker it contains."""

    def __init__(self, answers: dict[str, tuple[tuple[object, ...], ...]]) -> None:
        super().__init__()
        self._answers = answers

    async def fetch_one(
        self, statement: str, parameters: Mapping[str, object]
    ) -> tuple[object, ...] | None:
        rows = await self.fetch_all(statement, parameters)
        return rows[0] if rows else None

    async def fetch_all(
        self, statement: str, parameters: Mapping[str, object]
    ) -> tuple[tuple[object, ...], ...]:
        self._record(statement, parameters)
        for marker, rows in self._answers.items():
            if marker in statement:
                return rows
        return ()


class Reader(RowReader):
    """Expose the protected decoders to the test."""

    def uuid(self, value: object) -> UUID:
        return self._uuid(value)

    def instant(self, value: object) -> datetime:
        return self._instant(value)

    def ciphertext(self, value: object) -> bytes:
        return self._ciphertext(value)


class TestRowReader:
    def test_text_is_accepted_as_an_identifier(self) -> None:
        assert Reader().uuid(str(UUID(int=5))) == UUID(int=5)

    def test_a_naive_instant_is_refused(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            Reader().instant(datetime(2026, 1, 1))  # noqa: DTZ001 — the case

    def test_a_memoryview_is_ciphertext(self) -> None:
        assert Reader().ciphertext(memoryview(b"\x01abc")) == b"\x01abc"

    def test_text_is_not_ciphertext(self) -> None:
        with pytest.raises(ValueError, match="not bytes"):
            Reader().ciphertext("plain")

    def test_the_repository_base_offers_no_public_write(self) -> None:
        public = {name for name in dir(BaseRepository) if not name.startswith("_")}
        assert public == set()


class TestSealedValue:
    def test_sealed_json_opens_to_its_value(self) -> None:
        sealed = SealedValue(ReversibleCipher())
        envelope = sealed.seal_text('{"a":1,"b":"ñ"}')
        assert sealed.open_json(envelope) == {"a": 1, "b": "ñ"}

    def test_a_memoryview_envelope_opens(self) -> None:
        sealed = SealedValue(ReversibleCipher())
        envelope = memoryview(sealed.seal_text("hola"))
        assert sealed.open_text(envelope) == "hola"

    def test_text_is_not_an_envelope(self) -> None:
        with pytest.raises(ValueError, match="not bytes"):
            SealedValue(ReversibleCipher()).open_text("hola")

    def test_null_columns_stay_null(self) -> None:
        sealed = SealedValue(ReversibleCipher())
        assert sealed.seal_optional_text(None) is None
        assert sealed.open_optional_json(None) is None


class TestAuditRecordDecoder:
    def decoder(self) -> AuditRecordDecoder:
        return AuditRecordDecoder(SealedValue(ReversibleCipher()))

    def row(self) -> tuple[object, ...]:
        sealed = SealedValue(ReversibleCipher())
        record = Samples().stopped_audit_record()
        return (
            record.turn_id,
            record.session_id,
            0,
            sealed.seal_text(record.learner_prompt.text),
            sealed.seal_text("[]"),
            *(None,) * 9,
            record.policy_version,
            record.previous_record_hash,
            record.record_hash,
            WHEN,
            None,
        )

    def gate(self, name: str) -> tuple[object, ...]:
        sealed = SealedValue(ReversibleCipher())
        return (name, "pass", sealed.seal_text("ok"), "rule-1", WHEN)

    def test_four_gate_rows_decode_to_a_record(self) -> None:
        gates = tuple(self.gate(name) for name in GATE_ORDER)
        record = self.decoder().record(self.row(), gates, ())
        assert len(record.gate_evaluations) == 4

    def test_an_extra_gate_row_is_unreadable_not_a_crash(self) -> None:
        gates = tuple(self.gate(name) for name in (*GATE_ORDER, GATE_ORDER[0]))
        with pytest.raises(AuditRecordUnreadable) as raised:
            self.decoder().record(self.row(), gates, ())
        assert raised.value.turn_id == Samples().stopped_audit_record().turn_id

    def test_a_legacy_action_row_decodes_unchained(self) -> None:
        sealed = SealedValue(ReversibleCipher())
        row = (UUID(int=1), sealed.seal_text("t"), "approve", None, WHEN)
        action = self.decoder().action((*row, None, None, None, None))
        assert action.chained() is False


class TestPostgresAuditQuery:
    async def test_citations_return_the_curated_chunk_text(self) -> None:
        sealed = SealedValue(ReversibleCipher())
        row = (
            UUID(int=7),
            0,
            sealed.seal_text("Hola means hello."),
            UUID(int=8),
            "kb://greetings",
            "v1",
            "approved",
        )
        connection = ScriptedConnection((row,))
        query = PostgresAuditQuery(connection, AuditRecordDecoder(sealed))
        (snippet,) = await query.citations(UUID(int=1))
        assert snippet.content == "Hola means hello."
        assert snippet.source.source_uri == "kb://greetings"
        assert "JOIN kb_chunk" in connection.statements[0]


class ChainedAction:
    """A sealed action at a given chain position."""

    def at(self, kind: str, index: int, previous: str) -> HumanAction:
        unsealed = (
            Samples()
            .human_action()
            .model_copy(
                update={
                    "action": kind,
                    "session_id": SESSION_ID,
                    "action_index": index,
                    "previous_action_hash": previous,
                    "action_hash": "unsealed",
                }
            )
        )
        return unsealed.model_copy(
            update={"action_hash": ActionRecordHash().digest(unsealed)}
        )


class TestPostgresHumanAction:
    def adapter(self, connection: ScriptedConnection) -> PostgresHumanAction:
        return PostgresHumanAction(
            connection, SealedValue(ReversibleCipher()), ActionRecordHash()
        )

    async def test_an_empty_session_starts_at_genesis(self) -> None:
        head = await self.adapter(ScriptedConnection()).head(SESSION_ID)
        assert head.previous_action_hash == ActionRecordHash.GENESIS
        assert head.action_index == 0

    async def test_the_next_action_follows_the_last_one(self) -> None:
        head = await self.adapter(ScriptedConnection((("a" * 64, 2),))).head(SESSION_ID)
        assert head.previous_action_hash == "a" * 64
        assert head.action_index == 3

    async def test_an_unchained_action_is_refused_before_any_write(self) -> None:
        connection = ScriptedConnection()
        with pytest.raises(ActionRejected, match="chain position"):
            await self.adapter(connection).append(Samples().human_action())
        assert connection.statements == []

    async def test_a_forged_digest_is_refused(self) -> None:
        action = ChainedAction().at("approve", 0, ActionRecordHash.GENESIS)
        forged = action.model_copy(update={"tutor_id": "someone-else"})
        with pytest.raises(ActionRejected, match="canonical digest"):
            await self.adapter(ScriptedConnection()).append(forged)

    async def test_a_stale_link_is_refused(self) -> None:
        action = ChainedAction().at("approve", 0, ActionRecordHash.GENESIS)
        connection = ScriptedConnection((("b" * 64, 0),))
        with pytest.raises(ActionRejected, match="recorded first"):
            await self.adapter(connection).append(action)

    async def test_a_stop_takes_the_lock_inserts_then_marks_the_session(self) -> None:
        action = ChainedAction().at("stop", 0, ActionRecordHash.GENESIS)
        connection = ScriptedConnection()
        await self.adapter(connection).append(action)
        joined = [" ".join(statement.split()) for statement in connection.statements]
        assert "pg_advisory_xact_lock" in joined[0]
        assert any(s.startswith("INSERT INTO human_action") for s in joined)
        assert "mark_session_stopped" in joined[-1]

    @pytest.mark.parametrize(
        ("sqlstate", "message", "expected"),
        [
            ("HA001", "session is stopped", "session is stopped"),
            ("HA001", "the model did not run on this turn", "did not run"),
            ("23505", "duplicate key", "already has a tutor decision"),
        ],
    )
    async def test_a_database_refusal_is_an_action_rejection(
        self, sqlstate: str, message: str, expected: str
    ) -> None:
        action = ChainedAction().at("approve", 0, ActionRecordHash.GENESIS)
        connection = RefusingConnection(
            "INSERT INTO human_action", DriverError(sqlstate, message)
        )
        with pytest.raises(ActionRejected, match=expected):
            await self.adapter(connection).append(action)

    async def test_a_refused_stop_is_an_action_rejection(self) -> None:
        action = ChainedAction().at("stop", 0, ActionRecordHash.GENESIS)
        connection = RefusingConnection(
            "mark_session_stopped", DriverError("SS001", "session is stopped")
        )
        with pytest.raises(ActionRejected, match="session is stopped"):
            await self.adapter(connection).append(action)

    async def test_a_guard_refusal_without_a_message_has_a_fallback(self) -> None:
        action = ChainedAction().at("approve", 0, ActionRecordHash.GENESIS)
        error = DriverError("HA001", "")
        connection = RefusingConnection("INSERT INTO human_action", error)
        with pytest.raises(ActionRejected, match="cannot take this action"):
            await self.adapter(connection).append(action)

    async def test_an_unrelated_database_error_is_not_masked(self) -> None:
        action = ChainedAction().at("approve", 0, ActionRecordHash.GENESIS)
        connection = RefusingConnection(
            "INSERT INTO human_action", DriverError("08006", "connection lost")
        )
        with pytest.raises(DriverError):
            await self.adapter(connection).append(action)


class TestPostgresSessionDirectory:
    def adapter(self, connection: ScriptedConnection) -> PostgresSessionDirectory:
        return PostgresSessionDirectory(
            connection, SealedValue(ReversibleCipher()), FrozenClock(WHEN)
        )

    async def test_a_row_decodes_to_a_summary(self) -> None:
        row = (SESSION_ID, UUID(int=2), WHEN, None)
        (summary,) = await self.adapter(ScriptedConnection((row,))).listed()
        assert summary.open is True
        assert summary.started_at == WHEN

    async def test_the_list_is_newest_first(self) -> None:
        connection = ScriptedConnection()
        await self.adapter(connection).listed()
        assert "ORDER BY started_at DESC" in connection.statements[0]

    async def test_opening_seals_the_tutor_and_calls_the_definer(self) -> None:
        connection = ScriptedConnection()
        opening = SessionOpening(
            session_id=SESSION_ID,
            learner_id=UUID(int=2),
            tutor_id="tutor-1",
            started_at=WHEN,
        )
        await self.adapter(connection).open(opening)
        assert "open_session" in connection.statements[0]
        sealed = connection.parameters[0]["tutor_id"]
        assert isinstance(sealed, bytes)
        assert b"tutor-1" not in sealed[:1]

    async def test_a_refused_opening_is_session_open_rejected(self) -> None:
        connection = RefusingConnection(
            "open_session", DriverError("OS001", "learner retention has ended")
        )
        opening = SessionOpening(
            session_id=SESSION_ID,
            learner_id=UUID(int=2),
            tutor_id="tutor-1",
            started_at=WHEN,
        )
        with pytest.raises(SessionOpenRejected):
            await self.adapter(connection).open(opening)

    async def test_an_unrelated_opening_error_is_not_masked(self) -> None:
        connection = RefusingConnection(
            "open_session", DriverError("08006", "connection lost")
        )
        opening = SessionOpening(
            session_id=SESSION_ID,
            learner_id=UUID(int=2),
            tutor_id="tutor-1",
            started_at=WHEN,
        )
        with pytest.raises(DriverError):
            await self.adapter(connection).open(opening)

    async def test_retention_is_judged_at_the_injected_clock(self) -> None:
        rows = (
            (UUID(int=2), WHEN + timedelta(days=1)),
            (UUID(int=3), WHEN - timedelta(days=1)),
        )
        learners = await self.adapter(ScriptedConnection(rows)).learners()
        assert [learner.retained for learner in learners] == [True, False]


class TestPostgresCohortReport:
    async def test_the_counts_are_read_with_selects_only(self) -> None:
        connection = KeyedConnection(
            {"GROUP BY decision": (("pass", 4),), "FROM turn_audit": ((1, 0),)}
        )
        report = await PostgresCohortReport(connection).report()
        assert report.by_decision[0].rows == 4
        assert all(s.strip().startswith("SELECT") for s in connection.statements)


class TestRetentionPurge:
    async def test_a_learner_already_purged_is_not_selected_again(self) -> None:
        connection = ScriptedConnection()
        log = PurgeLog()
        await RetentionPurge(ReversibleCipher(), FrozenClock(WHEN), log).run(connection)
        assert "NOT EXISTS" in connection.statements[0]
        assert log.receipts == ()

    async def test_a_due_learner_is_purged_stopped_and_logged(self) -> None:
        connection = KeyedConnection(
            {
                "retain_until <= :now": ((UUID(int=2),),),
                "FROM learner_history_event": ((3,),),
                "FROM tutoring_session": ((1,),),
            }
        )
        log = PurgeLog()
        await RetentionPurge(ReversibleCipher(), FrozenClock(WHEN), log).run(connection)
        joined = " ".join(" ".join(s.split()) for s in connection.statements)
        assert "DELETE FROM learner_history_event" in joined
        assert "UPDATE tutoring_session SET stopped_at" in joined
        assert "INSERT INTO retention_purge" in joined
        assert log.receipts[0].learner_id == UUID(int=2)
        assert log.receipts[0].history_rows == 3
        assert log.receipts[0].sessions_stopped == 1


class TestChainSurvey:
    async def test_an_unreadable_session_is_reported_broken(self) -> None:
        record = SealedRecords().generated()
        connection = KeyedConnection(
            {
                "FROM policy_version": (("policy-1",),),
                "FROM tutoring_session": ((str(SESSION_ID),),),
            }
        )
        result = ChainSurveyResult()
        survey = ChainSurvey(
            MemoryAuditQuery((record,), unreadable=record.turn_id),
            ChainVerifier(AuditRecordHash(), ActionRecordHash()),
            result,
        )
        await survey.run(connection)
        assert result.chain_status() == "broken"
        assert result.broken_sessions == (SESSION_ID,)
        assert result.policy_version == "policy-1"

    async def test_an_empty_log_is_intact_with_no_policy(self) -> None:
        result = ChainSurveyResult()
        survey = ChainSurvey(
            MemoryAuditQuery(),
            ChainVerifier(AuditRecordHash(), ActionRecordHash()),
            result,
        )
        await survey.run(KeyedConnection({}))
        assert result.chain_status() == "intact"
        assert result.policy_version is None
