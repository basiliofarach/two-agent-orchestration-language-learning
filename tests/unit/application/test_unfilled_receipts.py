"""A unit of work that never runs its work must not look like an empty result.

Every dashboard execute stage reads inside a unit of work and then checks
the receipt the work fills. A unit that returns without running the work —
a broken adapter, a swallowed exception — would otherwise surface as an
empty session list or an intact empty audit. Each stage raises instead.
"""

from uuid import UUID

import pytest
from tests.support.dashboard_stubs import (
    SESSION_ID,
    ImmediateUnit,
    MemoryActions,
    MemoryAuditQuery,
    MemoryCohort,
    MemoryDirectory,
    SealedRecords,
)
from tests.support.turn_stubs import Agents

from tutor_api.adapters.frozen_clock import FrozenClock
from tutor_core.application.services.read_audit import (
    AuditCommand,
    ExecuteAudit,
    ExecuteTurnRead,
    PreparedAudit,
    TurnAuditCommand,
)
from tutor_core.application.services.record_human_action import (
    ActionRules,
    ExecuteAction,
    HumanActionBody,
    HumanActionCommand,
    PreparedAction,
)
from tutor_core.application.services.replay_turn import (
    DraftComparison,
    ExecuteReplay,
    ReplayCommand,
)
from tutor_core.application.services.report_cohort import (
    CohortCommand,
    ExecuteCohort,
)
from tutor_core.application.services.session_surface import (
    ExecuteLearnerList,
    ExecuteOpenSession,
    ExecuteSession,
    ExecuteSessionList,
    ExecuteStream,
    LearnerListCommand,
    OpenSessionCommand,
    PreparedOpening,
    PreparedSessions,
    PreparedStream,
    SessionCommand,
    SessionEvents,
    SseEncoder,
    StreamCommand,
)
from tutor_core.domain.audit.chain import ChainVerifier
from tutor_core.domain.audit.record_hash import ActionRecordHash, AuditRecordHash
from tutor_core.domain.ports.audit_query import TurnNotFound
from tutor_core.domain.ports.human_action import ActionRejected
from tutor_core.domain.ports.session_directory import SessionNotFound
from tutor_core.domain.ports.unit_of_work import TransactionalWork, UnitOfWorkPort


class SkippingUnit(UnitOfWorkPort):
    """Return without running the work."""

    async def run(self, work: TransactionalWork) -> None:
        return None


class TestUnfilledReceipts:
    async def test_the_session_list(self) -> None:
        with pytest.raises(ValueError, match="sessions were not read"):
            await ExecuteSessionList(SkippingUnit(), MemoryDirectory()).run(
                PreparedSessions()
            )

    async def test_one_session(self) -> None:
        with pytest.raises(SessionNotFound):
            await ExecuteSession(SkippingUnit(), MemoryDirectory()).run(
                SessionCommand(session_id=SESSION_ID)
            )

    async def test_an_opening(self) -> None:
        clock = FrozenClock(SealedRecords().generated().recorded_at)
        prepared = PreparedOpening(
            session_id=UUID(int=1),
            command=OpenSessionCommand(learner_id=UUID(int=2), tutor_id="t"),
        )
        with pytest.raises(ValueError, match="not opened"):
            await ExecuteOpenSession(SkippingUnit(), MemoryDirectory(), clock).run(
                prepared
            )

    async def test_the_learner_list(self) -> None:
        with pytest.raises(ValueError, match="learners were not read"):
            await ExecuteLearnerList(SkippingUnit(), MemoryDirectory()).run(
                LearnerListCommand()
            )

    async def test_the_stream(self) -> None:
        execute = ExecuteStream(
            SkippingUnit(),
            MemoryAuditQuery(),
            MemoryDirectory(),
            SessionEvents(),
            SseEncoder(),
        )
        prepared = PreparedStream(command=StreamCommand(session_id=SESSION_ID))
        with pytest.raises(ValueError, match="event stream was not read"):
            await execute.run(prepared)

    async def test_the_audit(self) -> None:
        execute = ExecuteAudit(
            SkippingUnit(),
            MemoryAuditQuery(),
            MemoryDirectory(),
            ChainVerifier(AuditRecordHash(), ActionRecordHash()),
        )
        prepared = PreparedAudit(command=AuditCommand(session_id=SESSION_ID))
        with pytest.raises(ValueError, match="audit log was not read"):
            await execute.run(prepared)

    async def test_the_turn_page(self) -> None:
        execute = ExecuteTurnRead(
            SkippingUnit(), MemoryAuditQuery(), MemoryDirectory(), AuditRecordHash()
        )
        with pytest.raises(ValueError, match="turn was not read"):
            await execute.run(TurnAuditCommand(turn_id=UUID(int=1)))

    async def test_an_action(self) -> None:
        query = MemoryAuditQuery()
        execute = ExecuteAction(
            SkippingUnit(),
            query,
            MemoryDirectory(),
            MemoryActions(query),
            FrozenClock(SealedRecords().generated().recorded_at),
            ActionRecordHash(),
            ActionRules(),
        )
        command = HumanActionCommand(
            session_id=SESSION_ID,
            turn_id=UUID(int=1),
            body=HumanActionBody(tutor_id="t", action="approve"),
        )
        with pytest.raises(ActionRejected, match="not recorded"):
            await execute.run(PreparedAction(command=command))

    async def test_a_replay(self) -> None:
        execute = ExecuteReplay(
            SkippingUnit(),
            MemoryAuditQuery(),
            Agents().generation(),
            AuditRecordHash(),
            DraftComparison(),
        )
        with pytest.raises(ValueError, match="turn was not read"):
            await execute.run(ReplayCommand(turn_id=UUID(int=1)))

    async def test_the_cohort(self) -> None:
        with pytest.raises(ValueError, match="cohort counts were not read"):
            await ExecuteCohort(SkippingUnit(), MemoryCohort()).run(CohortCommand())


class TestMissingRows:
    async def test_replaying_an_unknown_turn_is_not_found(self) -> None:
        execute = ExecuteReplay(
            ImmediateUnit(),
            MemoryAuditQuery(),
            Agents().generation(),
            AuditRecordHash(),
            DraftComparison(),
        )
        with pytest.raises(TurnNotFound):
            await execute.run(ReplayCommand(turn_id=UUID(int=1)))

    async def test_a_turn_whose_session_vanished_is_not_found(self) -> None:
        record = SealedRecords().generated()
        execute = ExecuteTurnRead(
            ImmediateUnit(),
            MemoryAuditQuery((record,)),
            MemoryDirectory(sessions=()),
            AuditRecordHash(),
        )
        with pytest.raises(SessionNotFound):
            await execute.run(TurnAuditCommand(turn_id=record.turn_id))

    async def test_an_excised_turn_is_named_as_the_break(self) -> None:
        first = SealedRecords().generated(0)
        orphan = SealedRecords().generated(2, "f" * 64)
        execute = ExecuteAudit(
            ImmediateUnit(),
            MemoryAuditQuery((first, orphan)),
            MemoryDirectory(),
            ChainVerifier(AuditRecordHash(), ActionRecordHash()),
        )
        view = await execute.run(
            PreparedAudit(command=AuditCommand(session_id=SESSION_ID))
        )
        assert view.intact is False
        assert view.break_reason == "excised"
        assert view.break_turn_id == orphan.turn_id
