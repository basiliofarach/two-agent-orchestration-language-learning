"""Injected clock. Replay does not call the wall clock."""

from abc import ABC, abstractmethod
from datetime import datetime


class ClockPort(ABC):
    """Supply the current time.

    Scope boundary: an injected clock so replay stays deterministic. This
    port carries no REQ-* of its own (DEC-0001). Callers pass the returned
    instant into records; models do not call ``datetime.now()``.
    """

    @abstractmethod
    def now(self) -> datetime:
        """Return the current timezone-aware instant."""
        raise NotImplementedError  # pragma: no cover
