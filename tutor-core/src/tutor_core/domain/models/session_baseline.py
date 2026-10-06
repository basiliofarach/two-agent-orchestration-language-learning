"""What the earlier turns of one session looked like (REQ-GATES)."""

from pydantic import BaseModel, ConfigDict, Field


class SessionBaseline(BaseModel):
    """The session norm the drift gate compares a turn with.

    Read from the session's sealed records before the turn runs. Counts and
    means only: no prompt, no output text, nothing about the learner
    (REQ-MINOR). The defaults are a new session, which has no norm yet.

    ``generated_turns`` counts drafts the model wrote; the two means are
    over those drafts and ``None`` when there is none. ``flagged_prompts``
    counts earlier prompts the classifier flagged at high severity.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    prior_turns: int = Field(default=0, ge=0)
    generated_turns: int = Field(default=0, ge=0)
    mean_support_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    mean_output_characters: float | None = Field(default=None, ge=0.0)
    flagged_prompts: int = Field(default=0, ge=0)
