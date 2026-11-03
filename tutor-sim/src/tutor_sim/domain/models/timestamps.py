"""Recorded instants are UTC. The harness does not import tutor_core (D-1)."""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator


class RequireTimezone:
    """Reject a naive datetime, including one whose offset is missing."""

    def __call__(self, value: datetime) -> datetime:
        if value.utcoffset() is None:
            msg = "timestamp must be timezone-aware"
            raise ValueError(msg)
        return value


class NormaliseToUtc:
    """One instant has one serialised form (DEC-0010)."""

    def __call__(self, value: datetime) -> datetime:
        return value.astimezone(UTC)


AwareDatetime = Annotated[
    datetime,
    AfterValidator(RequireTimezone()),
    AfterValidator(NormaliseToUtc()),
]
