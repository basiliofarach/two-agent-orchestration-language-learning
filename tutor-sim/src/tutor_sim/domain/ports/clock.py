"""Injected clock. A campaign does not call the wall clock."""

from abc import ABC, abstractmethod
from datetime import datetime


class ClockPort(ABC):
    """Supply the current time. Re-declared inside the harness (D-1)."""

    @abstractmethod
    def now(self) -> datetime:
        """Return the current timezone-aware instant."""
        raise NotImplementedError  # pragma: no cover
