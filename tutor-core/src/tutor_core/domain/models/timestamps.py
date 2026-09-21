"""Timestamps are supplied by the caller from ``ClockPort``.

Models do not call ``datetime.now()``. A naive datetime cannot be replayed,
so every recorded instant must carry a timezone. A ``tzinfo`` whose
``utcoffset`` is ``None`` is naive in effect and is rejected with the rest.

An accepted instant is then converted to UTC. ``12:00+02:00`` and
``10:00+00:00`` are the same instant, and the ``timestamptz`` column stores
them identically, but they serialise to different strings and so hash
differently. Canonicalising here keeps one instant to one digest, which is
what the Article 12 chain verifies (DEC-0010).
"""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator


class RequireTimezone:
    """Reject naive datetimes so a record does not depend on the host clock."""

    def __call__(self, value: datetime) -> datetime:
        if value.utcoffset() is None:
            msg = "timestamp must be timezone-aware"
            raise ValueError(msg)
        return value


class NormaliseToUtc:
    """Convert an accepted instant to UTC so its serialised form is canonical."""

    def __call__(self, value: datetime) -> datetime:
        return value.astimezone(UTC)


AwareDatetime = Annotated[
    datetime,
    AfterValidator(RequireTimezone()),
    AfterValidator(NormaliseToUtc()),
]
