"""In-memory dashboard ports, for service unit tests and port contracts."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from tests.support.samples import Samples
from tests.support.scripted_connection import ScriptedConnection
from tutor_core.domain.audit.record_hash import ActionRecordHash, AuditRecordHash
from tutor_core.domain.models.audit import (
    GATE_ORDER,
    ActionChainHead,
    GateEvaluation,
    GateOutcome,
    HumanAction,
    TurnAuditRecord,
)
from tutor_core.domain.models.cohort import CohortCount, CohortReport
from tutor_core.domain.models.retrieval import Snippet
from tutor_core.domain.models.session import (
    LearnerSummary,
    SessionOpening,
    SessionSummary,
)
from tutor_core.domain.ports.audit_query import AuditQueryPort, AuditRecordUnreadable
from tutor_core.domain.ports.cohort_report import CohortReportPort
from tutor_core.domain.ports.human_action import ActionRejected, HumanActionPort
from tutor_core.domain.ports.session_directory import (
    SessionDirectoryPort,
    SessionOpenRejected,
)
from tutor_core.domain.ports.unit_of_work import TransactionalWork, UnitOfWorkPort

SESSION_ID = UUID("00000000-0000-4000-8000-000000000004")
LEARNER_ID = UUID("00000000-0000-4000-8000-000000000001")
STARTED = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


class SealedRecords:
    """Sample records whose hashes are real, so a chain check passes."""

    def generated(
        self, turn_index: int = 0, previous: str | None = None
    ) -> TurnAuditRecord:
        sample = Samples().audit_record()
        return self._seal(
            sample.model_copy(
                update={
                    "turn_id": UUID(int=100 + turn_index),
                    "turn_index": turn_index,
                    "previous_record_hash": previous or AuditRecordHash.GENESIS,
                    "history_snapshot": Samples().history(),
                    "recorded_at": STARTED + timedelta(minutes=turn_index),
                    "gate_evaluations": self.gates("pass", "pass", "pass", "pass"),
                }
            )
        )

    def held(self, decision: GateOutcome = "pause") -> TurnAuditRecord:
        """A generated draft a post-generation gate held for review."""
        return self._seal(
            self.generated().model_copy(
                update={"gate_evaluations": self.gates("pass", "pass", decision)}
            )
        )

    def refused(self) -> TurnAuditRecord:
        """A draft the agent refused after the model ran; sensitivity stopped it."""
        return self._seal(
            self.generated().model_copy(
                update={
                    "refused": True,
                    "gate_evaluations": self.gates("pass", "pass", "stop"),
                }
            )
        )

    def legacy(self) -> TurnAuditRecord:
        """A generated draft sealed before gate rows were recorded."""
        return self._seal(self.generated().model_copy(update={"gate_evaluations": ()}))

    def gates(self, *decisions: GateOutcome) -> tuple[GateEvaluation, ...]:
        """One row per gate: the decisions given, then ``not_evaluated``."""
        padded = (*decisions, *("not_evaluated",) * (len(GATE_ORDER) - len(decisions)))
        return tuple(
            GateEvaluation(
                gate_name=name,
                decision=decision,
                reason=f"{name} {decision}",
                policy_rule_id=f"rule-{name}",
                evaluated_at=STARTED,
            )
            for name, decision in zip(GATE_ORDER, padded, strict=True)
        )

    def halted(
        self, turn_index: int = 0, previous: str | None = None
    ) -> TurnAuditRecord:
        sample = Samples().stopped_audit_record()
        return self._seal(
            sample.model_copy(
                update={
                    "turn_id": UUID(int=100 + turn_index),
                    "turn_index": turn_index,
                    "previous_record_hash": previous or AuditRecordHash.GENESIS,
                    "recorded_at": STARTED + timedelta(minutes=turn_index),
                }
            )
        )

    def _seal(self, record: TurnAuditRecord) -> TurnAuditRecord:
        hasher = AuditRecordHash()
        unsealed = record.model_copy(update={"record_hash": "unsealed"})
        return unsealed.model_copy(update={"record_hash": hasher.digest(unsealed)})


class MemoryAuditQuery(AuditQueryPort):
    """Records and actions held in memory. ``unreadable`` simulates tampering."""

    def __init__(
        self,
        records: tuple[TurnAuditRecord, ...] = (),
        actions: tuple[HumanAction, ...] = (),
        cited: tuple[Snippet, ...] = (),
        unreadable: UUID | None = None,
    ) -> None:
        self.records = list(records)
        self.stored_actions = list(actions)
        self._cited = cited
        self._unreadable = unreadable

    async def for_session(self, session_id: UUID) -> tuple[TurnAuditRecord, ...]:
        if self._unreadable is not None:
            raise AuditRecordUnreadable(self._unreadable)
        return tuple(r for r in self.records if r.session_id == session_id)

    async def turn(self, turn_id: UUID) -> TurnAuditRecord | None:
        return next((r for r in self.records if r.turn_id == turn_id), None)

    async def actions(self, turn_id: UUID) -> tuple[HumanAction, ...]:
        return tuple(a for a in self.stored_actions if a.turn_id == turn_id)

    async def session_actions(self, session_id: UUID) -> tuple[HumanAction, ...]:
        turns = {r.turn_id for r in self.records if r.session_id == session_id}
        return tuple(
            a
            for a in self.stored_actions
            if a.session_id == session_id or a.turn_id in turns
        )

    async def citations(self, turn_id: UUID) -> tuple[Snippet, ...]:
        return self._cited if any(r.turn_id == turn_id for r in self.records) else ()


class MemoryDirectory(SessionDirectoryPort):
    """Sessions and learners in memory. A learner not listed cannot be opened."""

    def __init__(
        self,
        sessions: tuple[SessionSummary, ...] | None = None,
        learners: tuple[LearnerSummary, ...] | None = None,
    ) -> None:
        self.sessions = list(
            sessions
            if sessions is not None
            else (
                SessionSummary(
                    session_id=SESSION_ID,
                    learner_id=LEARNER_ID,
                    started_at=STARTED,
                    open=True,
                ),
            )
        )
        self._learners = (
            learners
            if learners is not None
            else (LearnerSummary(learner_id=LEARNER_ID, retained=True),)
        )
        self.opened: list[SessionOpening] = []

    async def listed(self) -> tuple[SessionSummary, ...]:
        return tuple(sorted(self.sessions, key=lambda s: s.started_at, reverse=True))

    async def get(self, session_id: UUID) -> SessionSummary | None:
        return next((s for s in self.sessions if s.session_id == session_id), None)

    async def open(self, opening: SessionOpening) -> None:
        learner = next(
            (item for item in self._learners if item.learner_id == opening.learner_id),
            None,
        )
        if learner is None or not learner.retained:
            msg = "learner is not known, or their retention has ended"
            raise SessionOpenRejected(msg)
        self.opened.append(opening)
        self.sessions.append(
            SessionSummary(
                session_id=opening.session_id,
                learner_id=opening.learner_id,
                started_at=opening.started_at,
                open=True,
            )
        )

    async def learners(self) -> tuple[LearnerSummary, ...]:
        return self._learners

    def stop(self, session_id: UUID, at: datetime) -> None:
        """Test hook: mark a session stopped, as the definer would."""
        self.sessions = [
            s.model_copy(update={"stopped_at": at, "open": False})
            if s.session_id == session_id
            else s
            for s in self.sessions
        ]


class MemoryActions(HumanActionPort):
    """An action chain in memory. Appending checks the link, as the DB does."""

    def __init__(
        self, query: MemoryAuditQuery, directory: MemoryDirectory | None = None
    ) -> None:
        self._query = query
        self._directory = directory

    async def head(self, session_id: UUID) -> ActionChainHead:
        chained = [
            a
            for a in self._query.stored_actions
            if a.session_id == session_id and a.chained()
        ]
        if not chained:
            return ActionChainHead(
                previous_action_hash=ActionRecordHash.GENESIS, action_index=0
            )
        last = max(chained, key=lambda a: a.action_index or 0)
        return ActionChainHead(
            previous_action_hash=last.action_hash or "",
            action_index=(last.action_index or 0) + 1,
        )

    async def append(self, action: HumanAction) -> None:
        if action.session_id is None:
            msg = "an action is appended with its chain position"
            raise ActionRejected(msg)
        head = await self.head(action.session_id)
        if (
            action.previous_action_hash != head.previous_action_hash
            or action.action_index != head.action_index
        ):
            msg = "another action was recorded first; reload and try again"
            raise ActionRejected(msg)
        self._query.stored_actions.append(action)
        if action.action == "stop" and self._directory is not None:
            self._directory.stop(action.session_id, action.acted_at)


class MemoryCohort(CohortReportPort):
    """Fixed counts."""

    async def report(self) -> CohortReport:
        return CohortReport(
            by_decision=(CohortCount(decision="pass", rows=4),),
            refusals=0,
            turns=1,
        )


class ImmediateUnit(UnitOfWorkPort):
    """Run the work on a scripted connection. Records commit or rollback."""

    def __init__(self) -> None:
        self.committed = 0
        self.rolled_back = 0

    async def run(self, work: TransactionalWork) -> None:
        try:
            await work.run(ScriptedConnection())
        except Exception:
            self.rolled_back += 1
            raise
        self.committed += 1
