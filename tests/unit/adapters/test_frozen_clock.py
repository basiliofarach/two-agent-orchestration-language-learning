"""FrozenClock returns the instant it was given."""

from datetime import UTC, datetime

from tutor_api.adapters.frozen_clock import FrozenClock


class TestFrozenClock:
    def test_now_returns_the_injected_instant(self) -> None:
        instant = datetime(2026, 9, 21, 15, 30, tzinfo=UTC)
        clock = FrozenClock(instant)
        assert clock.now() == instant
        assert clock.now() == clock.now()
