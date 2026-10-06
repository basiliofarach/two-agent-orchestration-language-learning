"""Replay a recorded turn: generate again from the log and compare (REQ-AUDIT).

Rule 7 asks that a recorded turn replay from the audit log and reproduce
the same output. The record holds every input generation reads — the
redacted prompt, the cited chunks (by id, opened from the vetted corpus),
the allowlisted history snapshot — and the pins that make it repeatable:
template version, decoding parameters, model revision. Replay feeds those
back through the injected generation agent and reports, field by field,
whether the outputs match.

Gates are not re-run. Their inputs include the policy card and the
retrieval confidence of a search that would run against today's corpus;
the gate rows are already covered by the record's digest, which this use
case checks first.
"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from tutor_core.application.agents.generation import GenerationAgent
from tutor_core.application.services.service import (
    ApplicationService,
    ExecuteHandler,
    FinaliseHandler,
    PrepareHandler,
)
from tutor_core.domain.audit.record_hash import AuditRecordHash
from tutor_core.domain.models.audit import TurnAuditRecord
from tutor_core.domain.models.pipeline import GeneratedDraft
from tutor_core.domain.models.retrieval import RetrievalResult, Snippet
from tutor_core.domain.ports.audit_query import AuditQueryPort, TurnNotFound
from tutor_core.domain.ports.unit_of_work import (
    TransactionalWork,
    TransactionConnection,
    UnitOfWorkPort,
)

ReplayOutcome = Literal[
    "reproduced",
    "diverged",
    "not_generated",
    "history_not_recorded",
    "record_tampered",
]


class ReplayCommand(BaseModel):
    """Which turn to replay."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    turn_id: UUID


class ReplayReport(BaseModel):
    """What the replay found. ``checkpoint_id`` is the record's digest.

    ``differences`` names each recorded field the replay did not
    reproduce. ``not_generated`` means the turn halted or was refused
    before the model ran, so there is no output to reproduce; the record's
    digest still covers its gate rows.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    turn_id: UUID
    checkpoint_id: str
    outcome: ReplayOutcome
    differences: tuple[str, ...] = ()
    recorded_model_revision: str | None = None
    replay_model_revision: str | None = None


class ReplayInputs(BaseModel):
    """The record and the chunks it cited, read in one transaction."""

    model_config = ConfigDict(extra="forbid")

    record: TurnAuditRecord | None = None
    cited: tuple[Snippet, ...] = ()


class ReplayReadWork(TransactionalWork):
    """Read the record and its cited chunks. No write."""

    def __init__(
        self,
        command: ReplayCommand,
        inputs: ReplayInputs,
        query: AuditQueryPort,
    ) -> None:
        self._command = command
        self._inputs = inputs
        self._query = query

    async def run(self, connection: TransactionConnection) -> None:
        """Fill the inputs, or raise ``TurnNotFound``."""
        record = await self._query.turn(self._command.turn_id)
        if record is None:
            msg = "turn is not known"
            raise TurnNotFound(msg)
        self._inputs.record = record
        self._inputs.cited = await self._query.citations(record.turn_id)


class DraftComparison:
    """Name each recorded generation field a replayed draft does not match."""

    def differences(
        self, record: TurnAuditRecord, draft: GeneratedDraft
    ) -> tuple[str, ...]:
        """Return the names of the fields that differ, in record order."""
        unit = draft.unit
        pairs: tuple[tuple[str, object, object], ...] = (
            ("model_revision", record.model_revision, draft.model_revision),
            ("template_version", record.template_version, draft.template_version),
            ("decoding_params", record.decoding_params, draft.decoding_params),
            (
                "output_before_checks",
                record.output_before_checks,
                unit.output_before_checks,
            ),
            (
                "output_after_checks",
                record.output_after_checks,
                unit.output_after_checks,
            ),
            ("ai_disclosure", record.ai_disclosure, unit.ai_disclosure),
            ("refused", record.refused, unit.refused),
            ("safety_flags", record.safety_flags, draft.safety_flags),
            ("source_support", record.source_support, unit.support),
        )
        return tuple(name for name, kept, again in pairs if kept != again)


class PrepareReplay(PrepareHandler[ReplayCommand, ReplayCommand]):
    """The id is already a UUID."""

    def run(self, command: ReplayCommand) -> ReplayCommand:
        """Return the command."""
        return command


class ExecuteReplay(ExecuteHandler[ReplayCommand, ReplayReport]):
    """Read inside the unit of work, then generate outside it.

    The model call runs after the read transaction has closed, so a slow
    model does not hold the request's connection.
    """

    def __init__(
        self,
        unit: UnitOfWorkPort,
        query: AuditQueryPort,
        agent: GenerationAgent,
        hasher: AuditRecordHash,
        comparison: DraftComparison,
    ) -> None:
        self._unit = unit
        self._query = query
        self._agent = agent
        self._hasher = hasher
        self._comparison = comparison

    async def run(self, prepared: ReplayCommand) -> ReplayReport:
        """Return what the replay found."""
        inputs = ReplayInputs()
        await self._unit.run(ReplayReadWork(prepared, inputs, self._query))
        record = inputs.record
        if record is None:
            msg = "the turn was not read"
            raise ValueError(msg)
        if record.record_hash != self._hasher.digest(record):
            return self._report(record, "record_tampered")
        if record.output_after_checks is None:
            return self._report(record, "not_generated")
        history = record.history_snapshot
        if history is None:
            return self._report(record, "history_not_recorded")
        draft = await self._agent.generate(
            record.learner_prompt.text, self._context(inputs.cited), history
        )
        differences = self._comparison.differences(record, draft)
        return self._report(
            record,
            "diverged" if differences else "reproduced",
            differences,
            draft.model_revision,
        )

    def _report(
        self,
        record: TurnAuditRecord,
        outcome: ReplayOutcome,
        differences: tuple[str, ...] = (),
        replay_revision: str | None = None,
    ) -> ReplayReport:
        return ReplayReport(
            turn_id=record.turn_id,
            checkpoint_id=record.record_hash,
            outcome=outcome,
            differences=differences,
            recorded_model_revision=record.model_revision,
            replay_model_revision=replay_revision,
        )

    def _context(self, cited: tuple[Snippet, ...]) -> RetrievalResult:
        # The template renders snippets and their sources, not confidence;
        # the recorded turn's confidence was a gate input, which is not
        # replayed, so the neutral value is used.
        sources = tuple(dict.fromkeys(snippet.source for snippet in cited))
        return RetrievalResult(snippets=cited, sources=sources, confidence=0.0)


class FinaliseReplay(FinaliseHandler[ReplayReport, ReplayReport]):
    """The report is the result."""

    def run(self, executed: ReplayReport) -> ReplayReport:
        """Return the report."""
        return executed


class ReplayTurn(
    ApplicationService[ReplayCommand, ReplayCommand, ReplayReport, ReplayReport]
):
    """The container key for a turn replay. Adds no method (DEC-0011)."""
