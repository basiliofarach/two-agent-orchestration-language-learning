"""Contracts for the dashboard ports. Adapters subclass these; stubs pass here."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from tests.support.dashboard_stubs import (
    LEARNER_ID,
    SESSION_ID,
    MemoryActions,
    MemoryAuditQuery,
    MemoryCohort,
    MemoryDirectory,
    SealedRecords,
)
from tests.support.samples import Samples

from tutor_core.domain.audit.record_hash import ActionRecordHash
from tutor_core.domain.models.session import SessionOpening
from tutor_core.domain.ports.audit_query import AuditQueryPort
from tutor_core.domain.ports.cohort_report import CohortReportPort
from tutor_core.domain.ports.human_action import ActionRejected, HumanActionPort
from tutor_core.domain.ports.session_directory import SessionDirectoryPort

WHEN = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)


class AuditQueryPortContract:
    def port(self) -> AuditQueryPort:
        msg = "subclass must supply an AuditQueryPort"
        raise NotImplementedError(msg)

    async def test_an_unknown_turn_is_none(self) -> None:
        assert await self.port().turn(UUID(int=999_999)) is None

    async def test_a_session_reads_in_turn_order(self) -> None:
        records = await self.port().for_session(SESSION_ID)
        assert [r.turn_index for r in records] == sorted(r.turn_index for r in records)


class HumanActionPortContract:
    def port(self) -> HumanActionPort:
        msg = "subclass must supply a HumanActionPort"
        raise NotImplementedError(msg)

    async def test_an_empty_session_starts_at_genesis(self) -> None:
        head = await self.port().head(SESSION_ID)
        assert head.previous_action_hash == ActionRecordHash.GENESIS
        assert head.action_index == 0

    async def test_an_unchained_action_is_refused(self) -> None:
        with pytest.raises(ActionRejected):
            await self.port().append(Samples().human_action())


class SessionDirectoryPortContract:
    def port(self) -> SessionDirectoryPort:
        msg = "subclass must supply a SessionDirectoryPort"
        raise NotImplementedError(msg)

    async def test_an_opened_session_can_be_read_back(self) -> None:
        port = self.port()
        opening = SessionOpening(
            session_id=UUID(int=4242),
            learner_id=LEARNER_ID,
            tutor_id="tutor-1",
            started_at=WHEN,
        )
        await port.open(opening)
        read = await port.get(opening.session_id)
        assert read is not None
        assert read.open is True
        assert read.started_at == WHEN

    async def test_an_unknown_session_is_none(self) -> None:
        assert await self.port().get(UUID(int=31337)) is None


class CohortReportPortContract:
    def port(self) -> CohortReportPort:
        msg = "subclass must supply a CohortReportPort"
        raise NotImplementedError(msg)

    async def test_the_report_has_counts_and_no_verdict(self) -> None:
        report = await self.port().report()
        assert report.turns >= 0
        assert "verdict" not in type(report).model_fields


class TestMemoryAuditQuery(AuditQueryPortContract):
    def port(self) -> AuditQueryPort:
        first = SealedRecords().generated(0)
        return MemoryAuditQuery(
            (first, SealedRecords().generated(1, first.record_hash))
        )


class TestMemoryActions(HumanActionPortContract):
    def port(self) -> HumanActionPort:
        return MemoryActions(MemoryAuditQuery())


class TestMemoryDirectory(SessionDirectoryPortContract):
    def port(self) -> SessionDirectoryPort:
        return MemoryDirectory()


class TestMemoryCohort(CohortReportPortContract):
    def port(self) -> CohortReportPort:
        return MemoryCohort()
