"""ConductTurn: redact, run the gated graph, record, report (DEC-0011)."""

from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from tutor_core.application.services.service import (
    ApplicationService,
    ExecuteHandler,
    FinaliseHandler,
    PrepareHandler,
)
from tutor_core.application.turn.baseline import SessionBaselineCalculator
from tutor_core.application.turn.orchestrator import TurnOrchestrator
from tutor_core.application.turn.record import TurnRecordBuilder
from tutor_core.domain.models.conduct import (
    ExecutedTurn,
    PreparedTurn,
    TurnCommand,
    TurnOutcome,
)
from tutor_core.domain.models.learner import LearnerId
from tutor_core.domain.models.turn import TurnState
from tutor_core.domain.ports.audit_query import AuditQueryPort
from tutor_core.domain.ports.audit_sink import AuditSinkPort
from tutor_core.domain.ports.clock import ClockPort
from tutor_core.domain.ports.pii_redaction import PiiRedactionPort
from tutor_core.domain.ports.policy_artifact import PolicyArtifactPort
from tutor_core.domain.ports.safety_classifier import SafetyClassifierPort
from tutor_core.domain.ports.tutoring_session import (
    SessionRejected,
    TutoringSessionPort,
)
from tutor_core.domain.ports.unit_of_work import (
    TransactionalWork,
    TransactionConnection,
    UnitOfWorkPort,
)


class TurnFailed(Exception):
    """The turn did not complete. Its transaction rolled back; nothing was kept.

    Raised for any failure inside the unit of work — an unreadable policy
    card, the model runtime being unreachable, a rejected append. The turn
    and its audit record commit together or not at all (REQ-AUDIT), so a
    failed turn leaves no partial record and delivers nothing.
    """


class TurnReceipt(BaseModel):
    """Where a turn transaction leaves its result for the execute stage.

    ``UnitOfWorkPort.run`` returns nothing, so the work writes here. The
    receipt is empty until the work finished; after a rollback it stays
    empty.
    """

    model_config = ConfigDict(extra="forbid")

    executed: ExecutedTurn | None = None


class PrepareTurn(PrepareHandler[TurnCommand, PreparedTurn]):
    """Redact the prompt and state what the turn would need, before any read.

    The raw prompt stops here (REQ-MINOR). ``unvetted_source_categories``
    are the safety categories that mean the question needs material outside
    the vetted corpus — asking for the open web, for example. Setting
    ``requires_unvetted_source`` is a fact about the question; whether that
    stops the turn is the permission gate's decision, not this stage's.
    """

    def __init__(
        self,
        redactor: PiiRedactionPort,
        classifier: SafetyClassifierPort,
        unvetted_source_categories: tuple[str, ...],
    ) -> None:
        self._redactor = redactor
        self._classifier = classifier
        self._unvetted = unvetted_source_categories

    def run(self, command: TurnCommand) -> PreparedTurn:
        """Return the turn the graph starts from."""
        redacted = self._redactor.redact(command.prompt)
        flags = self._classifier.classify(redacted.text)
        return PreparedTurn(
            turn=TurnState(
                turn_id=uuid4(),
                session_id=command.session_id,
                learner_id=LearnerId(value=command.learner_id),
                learner_prompt=redacted,
                requested_history_fields=command.requested_history_fields,
                requires_unvetted_source=any(
                    flag.category in self._unvetted for flag in flags
                ),
                prompt_safety_flags=flags,
            )
        )


class TurnTransaction(TransactionalWork):
    """One turn's graph and its audit append, on one connection (DEC-0006).

    Built per execution from collaborators the execute handler was given; it
    constructs none. The graph's reads, the record, its gate rows and its
    citations commit together, or the unit of work rolls all of them back.
    """

    def __init__(  # noqa: PLR0913 — each collaborator is injected (rule 3)
        self,
        prepared: PreparedTurn,
        receipt: TurnReceipt,
        orchestrator: TurnOrchestrator,
        sink: AuditSinkPort,
        policy: PolicyArtifactPort,
        builder: TurnRecordBuilder,
        clock: ClockPort,
        sessions: TutoringSessionPort,
        query: AuditQueryPort,
        baselines: SessionBaselineCalculator,
    ) -> None:
        self._prepared = prepared
        self._receipt = receipt
        self._orchestrator = orchestrator
        self._sink = sink
        self._policy = policy
        self._builder = builder
        self._clock = clock
        self._sessions = sessions
        self._query = query
        self._baselines = baselines

    async def run(self, connection: TransactionConnection) -> None:
        """Confirm the session, run the graph, then append its record.

        The session check uses the enlisted connection and runs before the
        graph, so a missing, stopped, or foreign session never reaches
        retrieval (REQ-MINOR). ``connection`` is the same request connection
        the session port holds (DEC-0014). The session's earlier records are
        summarised onto the turn next, so the drift gate judges this turn
        against its own session (REQ-GATES).
        """
        turn = self._prepared.turn
        await self._sessions.require_active(turn.session_id, turn.learner_id)
        earlier = await self._query.for_session(turn.session_id)
        turn.session_baseline = self._baselines.baseline(earlier)
        state = await self._orchestrator.run(turn)
        head = await self._sink.head(turn.session_id)
        version = await self._policy.version()
        record = self._builder.build(state, head, version, self._clock.now())
        await self._sink.append(record)
        self._receipt.executed = ExecutedTurn(
            record=record,
            draft=state.draft,
            retrieved=state.turn.retrieved,
        )


class ExecuteTurn(ExecuteHandler[PreparedTurn, ExecutedTurn]):
    """Run the turn inside the request's unit of work.

    Gate order is the graph's (DEC-0005); this stage does not list gates.
    Logging every gate, run or not, is done here through the record
    builder, not by the gates.
    """

    def __init__(  # noqa: PLR0913 — each collaborator is injected (rule 3)
        self,
        unit: UnitOfWorkPort,
        orchestrator: TurnOrchestrator,
        sink: AuditSinkPort,
        policy: PolicyArtifactPort,
        builder: TurnRecordBuilder,
        clock: ClockPort,
        sessions: TutoringSessionPort,
        query: AuditQueryPort,
        baselines: SessionBaselineCalculator,
    ) -> None:
        self._unit = unit
        self._orchestrator = orchestrator
        self._sink = sink
        self._policy = policy
        self._builder = builder
        self._clock = clock
        self._sessions = sessions
        self._query = query
        self._baselines = baselines

    async def run(self, prepared: PreparedTurn) -> ExecutedTurn:
        """Commit the turn and its record, or raise ``TurnFailed``."""
        receipt = TurnReceipt()
        work = TurnTransaction(
            prepared,
            receipt,
            self._orchestrator,
            self._sink,
            self._policy,
            self._builder,
            self._clock,
            self._sessions,
            self._query,
            self._baselines,
        )
        try:
            await self._unit.run(work)
        except SessionRejected:
            raise
        except Exception as exc:
            msg = f"the turn did not complete ({type(exc).__name__}); nothing was kept"
            raise TurnFailed(msg) from exc
        if receipt.executed is None:
            msg = "the unit of work committed without running the turn"
            raise TurnFailed(msg)
        return receipt.executed


class FinaliseTurn(FinaliseHandler[ExecutedTurn, TurnOutcome]):
    """Report the turn to the tutor. Nothing here reaches the learner."""

    def run(self, executed: ExecutedTurn) -> TurnOutcome:
        """Map the committed record and draft to the dashboard's view."""
        record = executed.record
        draft = executed.draft
        halted = next(
            (row for row in record.gate_evaluations if row.decision != "pass"),
            None,
        )
        unit = None if draft is None else draft.unit
        retrieved = executed.retrieved
        return TurnOutcome(
            turn_id=record.turn_id,
            session_id=record.session_id,
            turn_index=record.turn_index,
            status="awaiting_tutor_approval" if halted is None else "held_for_review",
            halted_at=None if halted is None else halted.gate_name,
            reply=None if unit is None else unit.output_after_checks,
            ai_disclosure=None if unit is None else unit.ai_disclosure,
            refused=False if unit is None else unit.refused,
            unsupported_claims=(
                () if unit is None else tuple(s.text for s in unit.support.unsupported)
            ),
            sources=(
                ()
                if retrieved is None
                else tuple(source.source_uri for source in retrieved.sources)
            ),
            gates=record.gate_evaluations,
            policy_version=record.policy_version,
            model_revision=record.model_revision,
            record_hash=record.record_hash,
        )


class ConductTurn(
    ApplicationService[TurnCommand, PreparedTurn, ExecutedTurn, TurnOutcome]
):
    """The container key for the turn use case. Adds no method (DEC-0011)."""
