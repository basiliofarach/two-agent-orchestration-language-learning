"""One server-sent event the dashboard reads for a session (REQ-DASH)."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TurnStreamEvent(BaseModel):
    """A gate verdict or a draft, already redacted (REQ-MINOR, REQ-GATES).

    ``event_id`` is stable for the row, so a client that reconnects with
    ``Last-Event-ID`` does not paint the same verdict twice.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str = Field(min_length=1)
    kind: Literal["gate", "draft", "halt"]
    turn_id: UUID
    session_id: UUID
    gate_name: str | None = None
    decision: str | None = None
    text: str | None = None
