"""The wall clock returns UTC, never a host offset (DEC-0010)."""

from datetime import UTC

from tests.contract.test_port_contracts import ClockPortContract

from tutor_api.adapters.system_clock import SystemClock
from tutor_core.domain.ports.clock import ClockPort


class TestSystemClockContract(ClockPortContract):
    def port(self) -> ClockPort:
        return SystemClock()


class TestSystemClock:
    def test_now_is_utc_not_the_host_offset(self) -> None:
        instant = SystemClock().now()
        assert instant.tzinfo is UTC
        assert instant.utcoffset().total_seconds() == 0

    def test_successive_readings_do_not_go_backwards(self) -> None:
        clock = SystemClock()
        assert clock.now() <= clock.now()
