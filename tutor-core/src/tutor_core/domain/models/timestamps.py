"""Timestamps are supplied by the caller from ``ClockPort``.

Models do not call ``datetime.now()``. A naive datetime cannot be replayed,
so every recorded instant must carry a timezone.
"""

from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator


class RequireTimezone:
    """Reject naive datetimes so a record does not depend on the host clock."""

    def __call__(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            msg = "timestamp must be timezone-aware"
            raise ValueError(msg)
        return value


AwareDatetime = Annotated[datetime, AfterValidator(RequireTimezone())]
