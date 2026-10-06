"""What the evidence pack is allowed to copy out of the log."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field


class EvidenceSources(BaseModel):
    """What the manifest pins. Supplied by the command, not read ad hoc."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    commit: str = Field(min_length=1)
    lockfile_sha256: str = Field(min_length=64, max_length=64)
    model_revision: str = Field(min_length=1)
    runtime: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    chain_status: Literal["intact", "broken", "not_checked"]
    field_label: str = Field(min_length=1)
    sessions: int = Field(default=0, ge=0)
    turns: int = Field(default=0, ge=0)
    actions: int = Field(default=0, ge=0)
    unchained_actions: int = Field(default=0, ge=0)
    broken_sessions: tuple[str, ...] = ()


class SourceDocument(BaseModel):
    """One curated document as Article 10 may show it (REQ-KB).

    Source, version, and review status only. The reviewer is a person, so
    that name stays in the database.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_uri: str = Field(min_length=1)
    version: str = Field(min_length=1)
    review_status: Literal["pending", "approved", "rejected"]


class DecodingExcerpt(BaseModel):
    """The decoding parameters REQ-AUDIT requires on the turn."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    temperature: float = Field(ge=0.0)
    top_p: float = Field(ge=0.0, le=1.0)
    max_tokens: int = Field(ge=1)


class GateExcerpt(BaseModel):
    """One gate row. ``evaluated_at`` is the timestamp the log stored.

    The pack does not replace it. Today that timestamp is the turn's
    ``recorded_at``; recording the gate's own time is a separate change.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    gate_name: str = Field(min_length=1)
    decision: str = Field(min_length=1)
    policy_rule_id: str = Field(min_length=1)
    evaluated_at: str = Field(min_length=1)


class TurnExcerpt(BaseModel):
    """One turn, without the history snapshot and without flag messages.

    The prompt is the redacted text the log stored, passed through
    redaction again on the way out. Flag messages can quote the learner,
    so the pack keeps the category only. ``evaluated_at`` is copied, not
    invented.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    turn_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    turn_index: int = Field(ge=0)
    learner_prompt_redacted: str
    redacted_categories: tuple[str, ...]
    retrieved_context_ids: tuple[str, ...]
    context_digest: str | None = None
    model_revision: str | None = None
    template_version: str | None = None
    decoding_params: DecodingExcerpt | None = None
    output_before_checks: str | None = None
    output_after_checks: str | None = None
    ai_disclosure: str | None = None
    refused: bool | None = None
    safety_flag_categories: tuple[str, ...]
    prompt_safety_flag_categories: tuple[str, ...]
    unsupported_claims: int = Field(ge=0)
    policy_version: str = Field(min_length=1)
    previous_record_hash: str = Field(min_length=1)
    record_hash: str = Field(min_length=1)
    gates: tuple[GateExcerpt, ...]


class ActionExcerpt(BaseModel):
    """One tutor action. Edited text is redacted again before it is copied.

    ``tutor_id`` is the identifier the caller sent. The pack does not claim
    it proves who was at the keyboard.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    turn_id: str = Field(min_length=1)
    tutor_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    edited_output_redacted: str | None = None
    acted_at: str = Field(min_length=1)
    chained: bool


class PackBody(BaseModel):
    """The exhibits. Frozen so two renders of one read cannot diverge.

    ``rubric_label`` and ``field_comparison`` are fixed. A tutor-sourced
    comparison is not representable here: there is no field to put it in.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    documents: tuple[SourceDocument, ...]
    turns: tuple[TurnExcerpt, ...]
    actions: tuple[ActionExcerpt, ...]
    unreadable_sessions: tuple[str, ...]
    rubric_lines: tuple[str, ...] = ()
    rubric_label: Literal["synthetic-only"] = "synthetic-only"
    field_comparison: Literal["not_in_this_pack"] = "not_in_this_pack"

    @classmethod
    def empty(cls) -> Self:
        """A pack with nothing read yet. The label is still synthetic-only."""
        return cls(documents=(), turns=(), actions=(), unreadable_sessions=())
