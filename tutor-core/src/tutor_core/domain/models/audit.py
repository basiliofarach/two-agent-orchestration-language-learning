"""Append-only turn record and the tutor action appended after it (REQ-AUDIT)."""

from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tutor_core.domain.models.learner import LearnerHistorySnapshot
from tutor_core.domain.models.safety import (
    DecodingParams,
    SafetyFlag,
    SourceSupportReport,
    StoredLearnerPrompt,
)
from tutor_core.domain.models.timestamps import AwareDatetime, Timestamped
from tutor_core.domain.models.verdict import GateStage

TutorAction = Literal["approve", "edit", "override", "stop"]

GateOutcome = Literal["pass", "pause", "stop", "not_evaluated"]

# REQ-GATES order. A record's evaluations follow it, one row per gate.
GATE_ORDER: tuple[GateStage, ...] = (
    "context_and_permission",
    "conflict_and_ambiguity",
    "sensitivity_and_high_stakes",
    "drift_and_anomaly",
)


class ChainHead(BaseModel):
    """Where the next record in one session's chain attaches (REQ-AUDIT).

    ``previous_record_hash`` is the latest record's digest, or the genesis
    value for an empty session. ``turn_index`` is the index the next record
    must carry.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    previous_record_hash: str = Field(min_length=1)
    turn_index: int = Field(ge=0)


class GateEvaluation(Timestamped):
    """One gate's row in ``gate_evaluation`` (REQ-GATES, REQ-AUDIT).

    The log distinguishes *checked and passed* (``pass``), *checked and
    fired* (``pause`` or ``stop``) and *not reached* (``not_evaluated``).
    A gate that was not reached cites the rule of the verdict that halted
    the turn before it, so every row names the policy that explains it.
    """

    gate_name: GateStage
    decision: GateOutcome
    reason: str = Field(min_length=1)
    policy_rule_id: str = Field(min_length=1)
    evaluated_at: AwareDatetime


# Decisions on a turn's draft. A turn takes at most one; a stop may follow.
DECISIONS: frozenset[TutorAction] = frozenset({"approve", "edit", "override"})


class ActionChainHead(BaseModel):
    """Where the next tutor action in one session's chain attaches.

    The action chain runs beside the turn chain: one per session, starting
    at the genesis value, so an inserted, removed or back-dated action
    breaks it (REQ-AUDIT).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    previous_action_hash: str = Field(min_length=1)
    action_index: int = Field(ge=0)


class HumanAction(Timestamped):
    """What the tutor did, appended after the turn row.

    ``edited_output`` is the third text state on an edit. The row references
    ``turn_id``; it is not written by updating ``turn_audit``.

    ``session_id``, ``action_index``, ``previous_action_hash`` and
    ``action_hash`` place the action in its session's action chain. They
    are present together. A row written before the chain existed carries
    none of them and is reported as unchained, not as tampered.
    """

    turn_id: UUID
    tutor_id: str = Field(min_length=1)
    action: TutorAction
    edited_output: str | None = None
    acted_at: AwareDatetime
    session_id: UUID | None = None
    action_index: int | None = Field(default=None, ge=0)
    previous_action_hash: str | None = Field(default=None, min_length=1)
    action_hash: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def edit_carries_output(self) -> Self:
        if self.action != "edit":
            return self
        output = self.edited_output
        if output is None or not output.strip():
            msg = "edited_output is required when the tutor edits"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def chain_fields_agree(self) -> Self:
        """The four chain fields are present together, or absent together."""
        fields = (
            self.session_id,
            self.action_index,
            self.previous_action_hash,
            self.action_hash,
        )
        present = tuple(field is not None for field in fields)
        if any(present) and not all(present):
            msg = "an action is chained with all four fields, or with none"
            raise ValueError(msg)
        return self

    def chained(self) -> bool:
        """Whether this row is in an action chain (written after the chain)."""
        return self.action_hash is not None

    def decides(self) -> bool:
        """Whether this action is the turn's decision, rather than a stop."""
        return self.action in DECISIONS


class TurnAuditRecord(Timestamped):
    """Frozen per-turn log record (DEC-0002, REQ-AUDIT).

    ``learner_prompt`` stores the redacted prompt itself, not a digest. It is
    a ``StoredLearnerPrompt``, so a raw learner string is rejected (REQ-MINOR).
    ``recorded_at`` is supplied by the caller from ``ClockPort``.

    ``session_id`` and ``turn_index`` place the record in one session chain.
    ``gate_evaluations`` are the four gate rows, in the hash with the turn.
    ``retrieved_context_ids`` are ``Snippet.chunk_id`` values, the same
    identifiers ``turn_citation.chunk_id`` stores. Generation fields are
    absent together when the model did not run. That absence is stored as
    ``None`` and stays in the record the hash covers; a stop does not invent
    a revision or an output. The tutor action is a separate
    :class:`HumanAction` append and is not part of this record.

    ``history_snapshot`` is the allowlisted history the turn was generated
    with, kept so a replay renders the same prompt. It is ``None`` when
    retrieval never ran, and it was ``None`` on every record sealed before
    it was recorded.
    """

    turn_id: UUID
    session_id: UUID
    turn_index: int = Field(ge=0)
    learner_prompt: StoredLearnerPrompt
    retrieved_context_ids: tuple[str, ...]
    model_revision: str | None = Field(default=None, min_length=1)
    template_version: str | None = Field(default=None, min_length=1)
    decoding_params: DecodingParams | None = None
    output_before_checks: str | None = None
    output_after_checks: str | None = None
    ai_disclosure: str | None = None
    refused: bool | None = None
    safety_flags: tuple[SafetyFlag, ...] | None = None
    source_support: SourceSupportReport | None = None
    gate_evaluations: tuple[GateEvaluation, ...] = ()
    history_snapshot: LearnerHistorySnapshot | None = None
    policy_version: str = Field(min_length=1)
    previous_record_hash: str = Field(min_length=1)
    record_hash: str = Field(min_length=1)
    recorded_at: AwareDatetime

    @model_validator(mode="after")
    def generation_fields_agree(self) -> Self:
        fields = (
            self.model_revision,
            self.template_version,
            self.decoding_params,
            self.output_before_checks,
            self.output_after_checks,
            self.ai_disclosure,
            self.refused,
            self.safety_flags,
            self.source_support,
        )
        if any(field is not None for field in fields) and not all(
            field is not None for field in fields
        ):
            msg = "a turn the model never ran carries no model revision and no outputs"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def one_evaluation_per_gate(self) -> Self:
        """Either no gate rows, or all four in REQ-GATES order.

        Records sealed before gate rows existed carry none. A turn that ran
        the graph carries four: none is silently missing.
        """
        if not self.gate_evaluations:
            return self
        names = tuple(row.gate_name for row in self.gate_evaluations)
        if names != GATE_ORDER:
            msg = "gate evaluations must name each gate once, in REQ-GATES order"
            raise ValueError(msg)
        return self
