"""The port every registration implements. Written before any provider."""

from abc import ABC, abstractmethod
from collections.abc import Mapping

from tutor_api.di.lifetime import Lifetime


class Provider(ABC):
    """Supplies one dependency and declares how long it lives.

    Not a DEC-0001 port: this is an infrastructure ABC inside ``tutor_api``,
    like ``TransactionConnection``. It earns its place under rule 1 by having
    several implementations and by being the surface the lifetime check reads
    — a provider that could not state its lifetime could not be validated.
    """

    @abstractmethod
    def provides(self) -> type:
        """The type this provider satisfies, as asked for at a signature."""
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    def lifetime(self) -> Lifetime:
        """Whether the provided object lives for the process or one request."""
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    def requires(self) -> tuple[type, ...]:
        """The types this provider needs, declared so the graph is checkable."""
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    def create(self, resolved: Mapping[type, object]) -> object:
        """Build the object from its already-resolved requirements."""
        raise NotImplementedError  # pragma: no cover
