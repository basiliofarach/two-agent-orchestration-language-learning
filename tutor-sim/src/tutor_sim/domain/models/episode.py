"""What one closed-loop episode recorded. No model prose is a score."""

from pydantic import BaseModel, ConfigDict, Field


class EpisodeTurn(BaseModel):
    """One turn of an episode, in order."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    turn_index: int = Field(ge=0, le=7)
    prompt: str = Field(min_length=1)
    released: str | None = None
    halted_at: str | None = None
    decision: str = Field(min_length=1)


class EpisodeTranscript(BaseModel):
    """The turns that were submitted. A stop ends the episode."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    episode_id: str = Field(min_length=1)
    turns: tuple[EpisodeTurn, ...]
    stopped: bool
