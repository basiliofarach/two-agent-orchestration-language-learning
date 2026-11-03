"""A fixed instant behind ``ClockPort``."""

from datetime import datetime

from tutor_sim.domain.ports.clock import ClockPort


class FrozenClock(ClockPort):
    """Return one injected instant on every call."""

    def __init__(self, instant: datetime) -> None:
        self._instant = instant

    def now(self) -> datetime:
        """Return the instant this clock was given."""
        return self._instant
