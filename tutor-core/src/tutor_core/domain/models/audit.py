"""Append-only turn record and the tutor action attached to it (REQ-AUDIT)."""

from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tutor_core.domain.models.safety import DecodingParams, SafetyFlag
from tutor_core.domain.models.timestamps import AwareDatetime

TutorAction = Literal["approve", "edit", "override", "stop"]


class HumanAction(BaseModel):
    """What the tutor did. ``edited_output`` is the third text state on an edit."""

    model_config = ConfigDict(frozen=True, extra="forbid")

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
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    turn_id: UUID
    learner_prompt_redacted: str
    redacted_categories: tuple[str, ...]
    retrieved_context_ids: tuple[str, ...]
    model_revision: str = Field(min_length=1)
    decoding_params: DecodingParams
    output_before_checks: str
    output_after_checks: str
    safety_flags: tuple[SafetyFlag, ...]
    human_action: HumanAction | None
    policy_version: str = Field(min_length=1)
    previous_record_hash: str = Field(min_length=1)
    record_hash: str = Field(min_length=1)
    recorded_at: AwareDatetime
