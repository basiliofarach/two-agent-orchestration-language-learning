"""A fixed instant behind ``ClockPort``. Replay does not read the wall clock."""

from datetime import datetime

from tutor_core.domain.ports.clock import ClockPort


class FrozenClock(ClockPort):
    """Return one injected instant on every call (DEC-0010).

    Callers copy that instant onto the record. The audit sink reads
    ``recorded_at`` from the record and does not call the wall clock.
    """

    def __init__(self, instant: datetime) -> None:
        self._instant = instant

    def now(self) -> datetime:
        """Return the instant this clock was given."""
        return self._instant
