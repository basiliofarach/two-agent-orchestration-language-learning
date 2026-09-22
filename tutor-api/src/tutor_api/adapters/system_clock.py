"""Wall clock behind ``ClockPort``. Replay tests substitute a fixed clock."""

from datetime import UTC, datetime

from tutor_core.domain.ports.clock import ClockPort


class SystemClock(ClockPort):
    """The current UTC instant.

    UTC rather than the host offset: resolving a naive local time through
    ``astimezone`` is ambiguous in a DST fold, and a recorded instant reaches
    a digest (DEC-0010). ``AwareDatetime`` normalises to UTC in any case.
    """

    def now(self) -> datetime:
        """Return the current instant in UTC."""
        return datetime.now(UTC)
