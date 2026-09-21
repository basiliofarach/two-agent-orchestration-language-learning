"""A ``tzinfo`` that is attached but carries no offset (DEC-0010, replay)."""

from datetime import datetime, timedelta, tzinfo


class OffsetlessTimezone(tzinfo):
    """Set on a datetime yet naive in effect: ``utcoffset`` is ``None``."""

    def utcoffset(self, dt: datetime | None) -> timedelta | None:
        return None

    def tzname(self, dt: datetime | None) -> str | None:
        return "OFFSETLESS"

    def dst(self, dt: datetime | None) -> timedelta | None:
        return None
