"""A session is accepted only when it is this learner's and still open."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from tests.contract.test_port_contracts import TutoringSessionPortContract
from tests.support.samples import Samples
from tests.support.scripted_connection import ScriptedConnection

from tutor_api.adapters.persistence.tutoring_session import PostgresTutoringSession
from tutor_core.domain.ports.tutoring_session import (
    SessionRejected,
    TutoringSessionPort,
)

_STOPPED = datetime(2026, 10, 6, tzinfo=UTC)
_OTHER = UUID("00000000-0000-4000-8000-000000000099")


class TestPostgresTutoringSessionContract(TutoringSessionPortContract):
    def port(self) -> TutoringSessionPort:
        return PostgresTutoringSession(
            ScriptedConnection(((Samples().learner_id().value, None),))
        )


class TestPostgresTutoringSession:
    def _port(
        self, row: tuple[object, ...] | None
    ) -> tuple[PostgresTutoringSession, ScriptedConnection]:
        rows = () if row is None else (row,)
        connection = ScriptedConnection(rows)
        return PostgresTutoringSession(connection), connection

    async def test_an_open_session_for_this_learner_is_accepted(self) -> None:
        port, connection = self._port((Samples().learner_id().value, None))
        await port.require_active(Samples().turn().session_id, Samples().learner_id())
        assert "tutoring_session" in connection.statements[0]
        assert "tutor_id" not in connection.statements[0]
        assert "stop_reason" not in connection.statements[0]
        assert "UPDATE" not in connection.statements[0].upper()

    async def test_a_missing_session_is_rejected(self) -> None:
        port, _connection = self._port(None)
        with pytest.raises(SessionRejected, match="not known"):
            await port.require_active(
                Samples().turn().session_id, Samples().learner_id()
            )

    async def test_another_learners_session_is_rejected(self) -> None:
        port, _connection = self._port((_OTHER, None))
        with pytest.raises(SessionRejected, match="different learner"):
            await port.require_active(
                Samples().turn().session_id, Samples().learner_id()
            )

    async def test_a_stopped_session_is_rejected(self) -> None:
        port, _connection = self._port((Samples().learner_id().value, _STOPPED))
        with pytest.raises(SessionRejected, match="stopped"):
            await port.require_active(
                Samples().turn().session_id, Samples().learner_id()
            )

    async def test_a_learner_id_stored_as_text_is_accepted(self) -> None:
        port, _connection = self._port((str(Samples().learner_id().value), None))
        await port.require_active(Samples().turn().session_id, Samples().learner_id())

    async def test_a_learner_id_that_is_not_an_identifier_is_refused(self) -> None:
        port, _connection = self._port((1, None))
        with pytest.raises(ValueError, match="not an identifier"):
            await port.require_active(
                Samples().turn().session_id, Samples().learner_id()
            )

    async def test_a_stop_time_that_is_not_a_timestamp_is_refused(self) -> None:
        port, _connection = self._port((Samples().learner_id().value, 1))
        with pytest.raises(ValueError, match="not a timestamp"):
            await port.require_active(
                Samples().turn().session_id, Samples().learner_id()
            )

    async def test_a_naive_stop_time_is_refused(self) -> None:
        port, _connection = self._port(
            (Samples().learner_id().value, datetime(2026, 10, 6))
        )
        with pytest.raises(ValueError, match="timezone-aware"):
            await port.require_active(
                Samples().turn().session_id, Samples().learner_id()
            )
