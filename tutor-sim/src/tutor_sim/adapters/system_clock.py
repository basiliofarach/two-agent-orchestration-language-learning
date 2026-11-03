"""Wall clock behind ``ClockPort``. Campaign tests substitute a fixed clock."""

from datetime import UTC, datetime

from tutor_sim.domain.ports.clock import ClockPort


class SystemClock(ClockPort):
    """The current UTC instant."""

    def now(self) -> datetime:
        """Return the current instant in UTC."""
        return datetime.now(UTC)
