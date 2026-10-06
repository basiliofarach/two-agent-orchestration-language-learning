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
from typing import Annotated, get_args, get_origin

from pydantic import AfterValidator, BaseModel, ConfigDict


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


class InstantAnnotation:
    """The ``datetime`` values one annotation holds, and which are aware.

    Pydantic strips the outer ``Annotated`` into ``FieldInfo.metadata``, so
    that metadata is passed in. An inner ``Annotated`` (``AwareDatetime |
    None``, ``tuple[AwareDatetime, ...]``) carries its own.
    """

    def __init__(self, annotation: object, metadata: tuple[object, ...] = ()) -> None:
        self._annotation = annotation
        self._metadata = metadata

    def instants(self) -> tuple[bool, ...]:
        """One flag per ``datetime`` reached: true when it is ``AwareDatetime``."""
        if get_origin(self._annotation) is Annotated:
            inner, *extra = get_args(self._annotation)
            return InstantAnnotation(inner, (*self._metadata, *extra)).instants()
        if isinstance(self._annotation, type) and issubclass(
            self._annotation, datetime
        ):
            return (self._aware(),)
        return tuple(
            flag
            for argument in get_args(self._annotation)
            for flag in InstantAnnotation(argument).instants()
        )

    def _aware(self) -> bool:
        return any(
            isinstance(item, AfterValidator) and isinstance(item.func, RequireTimezone)
            for item in self._metadata
        )


class InstantFields:
    """A model's fields that hold a ``datetime``, split by awareness."""

    def __init__(self, model: type[BaseModel]) -> None:
        self._model = model

    def aware(self) -> tuple[str, ...]:
        """Fields whose every ``datetime`` is ``AwareDatetime``."""
        return tuple(name for name, flags in self._flags() if flags and all(flags))

    def naive(self) -> tuple[str, ...]:
        """Fields holding a ``datetime`` that is not ``AwareDatetime``."""
        return tuple(name for name, flags in self._flags() if not all(flags))

    def _flags(self) -> tuple[tuple[str, tuple[bool, ...]], ...]:
        fields = self._model.model_fields.items()
        return tuple(
            (name, InstantAnnotation(info.annotation, tuple(info.metadata)).instants())
            for name, info in fields
        )


class Timestamped(BaseModel):
    """Frozen record that stores its instants as ``AwareDatetime`` (DEC-0010).

    Subclasses name the instant. ``recorded_at``, ``occurred_at``,
    ``evaluated_at`` and ``acted_at`` are different columns, so they are not
    one inherited field. What they share is this config and the check below:
    a subclass with a plain ``datetime``, or with no instant at all, is a
    ``TypeError`` when the class is defined, not when a row is replayed. An
    audit row is append-only, so this base has no ``updated_at``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: object) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        fields = InstantFields(cls)
        naive = fields.naive()
        if naive:
            msg = (
                f"{cls.__name__}.{', '.join(naive)} is a datetime without "
                "AwareDatetime (DEC-0010)"
            )
            raise TypeError(msg)
        if not fields.aware():
            msg = f"{cls.__name__} inherits Timestamped but stores no AwareDatetime"
            raise TypeError(msg)
