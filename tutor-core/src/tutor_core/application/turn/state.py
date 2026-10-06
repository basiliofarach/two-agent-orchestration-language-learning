"""Graph state: the live turn plus the graph's own bookkeeping (DEC-0010)."""

from pydantic import BaseModel, ConfigDict

from tutor_core.domain.models.pipeline import GeneratedDraft
from tutor_core.domain.models.turn import TurnState
from tutor_core.domain.models.verdict import GateVerdict


class TurnGraphState(BaseModel):
    """What LangGraph carries between nodes. Not a domain model.

    ``verdicts`` are appended in the order the gates ran. A turn halted at a
    gate has that gate's verdict last and no later one. ``draft`` keeps the
    pins (template, revision, decoding) the turn itself has no field for.
    """

    model_config = ConfigDict(extra="forbid")

    turn: TurnState
    verdicts: tuple[GateVerdict, ...] = ()
    draft: GeneratedDraft | None = None

    def halted(self) -> bool:
        """Whether the last gate that ran returned anything but ``pass``."""
        return bool(self.verdicts) and self.verdicts[-1].decision != "pass"
