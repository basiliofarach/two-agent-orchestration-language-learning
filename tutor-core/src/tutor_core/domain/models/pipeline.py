"""What one guarded stage returns. A halt carries no later-stage product."""

from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from tutor_core.domain.models.retrieval import RetrievedContext
from tutor_core.domain.models.safety import DecodingParams, GeneratedUnit, SafetyFlag
from tutor_core.domain.models.verdict import GateVerdict


class GuardedRetrievalResult(BaseModel):
    """The permission verdict, and retrieval only when that verdict passed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: GateVerdict
    context: RetrievedContext | None

    @model_validator(mode="after")
    def retrieval_follows_a_pass(self) -> Self:
        """A non-pass verdict has no retrieved context (REQ-GATES)."""
        passed = self.verdict.decision == "pass"
        if passed and self.context is None:
            msg = "a passing permission verdict has no retrieved context"
            raise ValueError(msg)
        if not passed and self.context is not None:
            msg = "retrieval ran after a non-pass permission verdict"
            raise ValueError(msg)
        return self


class GeneratedDraft(BaseModel):
    """The generation agent's product: the unit, the flags, the pins.

    ``template_version``, ``model_revision`` and ``decoding_params`` are
    present together when the model was called and absent together when it
    was not. A refusal before the model runs records no revision it did not
    use (REQ-AUDIT). The disclosure on ``unit`` is present either way
    (REQ-MINOR).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    unit: GeneratedUnit
    safety_flags: tuple[SafetyFlag, ...]
    template_version: str | None = None
    model_revision: str | None = None
    decoding_params: DecodingParams | None = None

    @model_validator(mode="after")
    def pins_travel_together(self) -> Self:
        """The model ran, with every pin, or it did not run at all."""
        pins = (self.template_version, self.model_revision, self.decoding_params)
        ran = self.unit.output_before_checks is not None
        if ran and any(pin is None for pin in pins):
            msg = "a model output needs its template, revision and decoding"
            raise ValueError(msg)
        if not ran and any(pin is not None for pin in pins):
            msg = "a draft the model did not write carries no model pins"
            raise ValueError(msg)
        return self

    def model_ran(self) -> bool:
        """Whether the language model was called for this draft."""
        return self.unit.output_before_checks is not None


class GuardedGenerationResult(BaseModel):
    """The conflict verdict, and a draft only when that verdict passed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: GateVerdict
    draft: GeneratedDraft | None

    @model_validator(mode="after")
    def generation_follows_a_pass(self) -> Self:
        """A non-pass verdict has no draft (REQ-GATES)."""
        passed = self.verdict.decision == "pass"
        if passed and self.draft is None:
            msg = "a passing conflict verdict has no draft"
            raise ValueError(msg)
        if not passed and self.draft is not None:
            msg = "generation ran after a non-pass conflict verdict"
            raise ValueError(msg)
        return self
