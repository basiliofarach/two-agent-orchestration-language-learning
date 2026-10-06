"""Rule identifiers a gate resolves on the policy card (REQ-POLICY)."""

from pydantic import BaseModel, ConfigDict, Field


class PermissionRuleIds(BaseModel):
    """The rules the permission gate may cite. No identifier has a default."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    in_scope: str = Field(min_length=1)
    unvetted_source: str = Field(min_length=1)
    history_outside_minimum: str = Field(min_length=1)
    indeterminate: str = Field(min_length=1)
    evaluation_failed: str = Field(min_length=1)


class ConflictRuleIds(BaseModel):
    """The rules the conflict gate may cite, including the threshold rule."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sufficient: str = Field(min_length=1)
    empty: str = Field(min_length=1)
    low_confidence: str = Field(min_length=1)
    contradiction: str = Field(min_length=1)
    evaluation_failed: str = Field(min_length=1)
    threshold: str = Field(min_length=1)


class SensitivityRuleIds(BaseModel):
    """The rules the sensitivity gate may cite."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    routine: str = Field(min_length=1)
    flagged_category: str = Field(min_length=1)
    refused: str = Field(min_length=1)
    evaluation_failed: str = Field(min_length=1)


class DriftRuleIds(BaseModel):
    """The rules the drift gate may cite."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    within_envelope: str = Field(min_length=1)
    outside_envelope: str = Field(min_length=1)
    outside_session_envelope: str = Field(min_length=1)
    evaluation_failed: str = Field(min_length=1)


class DriftEnvelope(BaseModel):
    """The behaviour one turn is expected to stay inside (REQ-GATES).

    Retrieval confidence and source support must not fall below their
    floors; the draft must not exceed its length or its grammar findings.
    These bounds hold for any turn. :class:`SessionEnvelope` is the bound
    relative to the session's own earlier turns.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_retrieval_confidence: float = Field(ge=0.0, le=1.0)
    min_support_ratio: float = Field(ge=0.0, le=1.0)
    max_output_characters: int = Field(ge=1)
    max_grammar_findings: int = Field(ge=0)


class SessionEnvelope(BaseModel):
    """How far a turn may leave its session's norm (REQ-GATES, §13).

    REQ-GATES scopes drift to the session. Once the session has
    ``min_prior_turns`` drafts, a draft whose source support falls more than
    ``max_support_drop`` below the session mean, or that is longer than
    ``max_length_factor`` times the session's mean length, is outside it.
    ``max_flagged_prompts`` earlier high-severity prompts in one session
    are a pattern — repeated attempts — whatever this turn looks like.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_prior_turns: int = Field(ge=1)
    max_support_drop: float = Field(ge=0.0, le=1.0)
    max_length_factor: float = Field(ge=1.0)
    max_flagged_prompts: int = Field(ge=1)
