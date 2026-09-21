"""Generation, disclosure, and the checks that inspect a draft."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DecodingParams(BaseModel):
    """Decoding parameters recorded on the audit log (REQ-AUDIT).

    The in-memory shape is this model (ARCHITECTURE §5). Callers supply it;
    nothing here reads the clock.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    temperature: float = Field(ge=0.0)
    top_p: float = Field(ge=0.0, le=1.0)
    max_tokens: int = Field(ge=1)


class SafetyFlag(BaseModel):
    """A safety or out-of-scope flag raised by the classifier, not by a gate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    category: str = Field(min_length=1)
    message: str = Field(min_length=1)
    severity: Literal["low", "medium", "high"]


class GrammarFinding(BaseModel):
    """One grammar finding. The check reports it; it does not rewrite the draft."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    message: str = Field(min_length=1)
    offset: int = Field(ge=0)
    length: int = Field(ge=0)
    replacement: str | None = None


class ClaimSpan(BaseModel):
    """A span of generated text, with the sources that support it when any do."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    source_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def end_follows_start(self) -> Self:
        if self.end < self.start:
            msg = "end must be greater than or equal to start"
            raise ValueError(msg)
        return self


class SourceSupportReport(BaseModel):
    """Supported and unsupported claim spans (REQ-ACCURACY).

    Unsupported spans stay on the report so a tutor can review them. They
    are not dropped.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    supported: tuple[ClaimSpan, ...]
    unsupported: tuple[ClaimSpan, ...]
    support_ratio: float = Field(ge=0.0, le=1.0)


class RedactedText(BaseModel):
    """Learner text after PII redaction, plus what was removed (REQ-MINOR)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    redacted_categories: tuple[str, ...]
    redaction_count: int = Field(ge=0)

    @model_validator(mode="after")
    def categories_match_count(self) -> Self:
        if self.redaction_count == 0:
            if self.redacted_categories:
                msg = "redacted_categories must be empty when redaction_count is 0"
                raise ValueError(msg)
            return self
        if not self.redacted_categories:
            msg = "redacted_categories are required when redaction_count is positive"
            raise ValueError(msg)
        return self


class RenderedPrompt(BaseModel):
    """A fixed template after rendering, with the template version to log."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=1)
    template_version: str = Field(min_length=1)


class ModelCompletion(BaseModel):
    """Text from the language model, with the revision and decoding used."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    model_revision: str = Field(min_length=1)
    decoding_params: DecodingParams


class GeneratedUnit(BaseModel):
    """Draft before and after checks, disclosure, refusal, and findings.

    ``ai_disclosure`` is present on every output, including a refusal
    (REQ-MINOR, REQ-COMP).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    output_before_checks: str
    output_after_checks: str
    ai_disclosure: str
    refused: bool
    refusal_reason: str | None
    support: SourceSupportReport
    grammar: tuple[GrammarFinding, ...]

    @model_validator(mode="after")
    def disclosure_and_refusal(self) -> Self:
        if not self.ai_disclosure.strip():
            msg = "ai_disclosure is required on every output"
            raise ValueError(msg)
        if self.refused:
            reason = self.refusal_reason
            if reason is None or not reason.strip():
                msg = "refusal_reason is required when refused"
                raise ValueError(msg)
            return self
        if self.refusal_reason is not None:
            msg = "refusal_reason must be absent unless refused"
            raise ValueError(msg)
        return self
