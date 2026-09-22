"""Append-only turn record and the tutor action appended after it (REQ-AUDIT)."""

from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tutor_core.domain.models.safety import (
    DecodingParams,
    SafetyFlag,
    SourceSupportReport,
)
from tutor_core.domain.models.timestamps import AwareDatetime

TutorAction = Literal["approve", "edit", "override", "stop"]


class HumanAction(BaseModel):
    """What the tutor did, appended after the turn row.

    ``edited_output`` is the third text state on an edit. The row references
    ``turn_id``; it is not written by updating ``turn_audit``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    turn_id: UUID
    tutor_id: str = Field(min_length=1)
    action: TutorAction
    edited_output: str | None = None
    acted_at: AwareDatetime

    @model_validator(mode="after")
    def edit_carries_output(self) -> Self:
        if self.action != "edit":
            return self
        output = self.edited_output
        if output is None or not output.strip():
            msg = "edited_output is required when the tutor edits"
            raise ValueError(msg)
        return self


class TurnAuditRecord(BaseModel):
    """Frozen per-turn log record (DEC-0002, REQ-AUDIT).

    ``learner_prompt_redacted`` stores the redacted prompt itself, not a
    digest. ``recorded_at`` is supplied by the caller from ``ClockPort``.

    ``session_id`` and ``turn_index`` place the record in one session chain.
    Generation fields are absent together when the model did not run. That
    absence is stored as ``None`` and stays in the record the hash covers; a
    stop does not invent a revision or an output. The tutor action is a
    separate :class:`HumanAction` append and is not part of this record.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    turn_id: UUID
    session_id: UUID
    turn_index: int = Field(ge=0)
    learner_prompt_redacted: str
    redacted_categories: tuple[str, ...]
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
