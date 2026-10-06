"""Base providers for the two registrations every use case repeats.

A use case is three stage handlers and the ``ApplicationService`` that
holds them (DEC-0011). Written out by hand that is four providers of twenty
lines each, and the twenty lines say the same thing every time. These two
bases say it once.

They are not auto-wiring. DEC-0013 rejects a container that discovers what
to build; here every registration still names its concrete class and the
exact types it requires, in ``container.py``, where the lifetime check can
read them. Nothing is inspected: ``requires()`` returns what the caller
wrote, and ``create`` passes the resolved objects positionally in that
order.
"""

from collections.abc import Mapping

from tutor_api.di.lifetime import Lifetime
from tutor_api.di.provider import Provider


class StatelessProvider(Provider):
    """A singleton built with no arguments: a prepare or finalise handler.

    Such a handler holds nothing, so one instance serves every request and
    cannot carry one learner's data into another's (DEC-0013).
    """

    def __init__(self, implementation: type) -> None:
        self._implementation = implementation

    def provides(self) -> type:
        return self._implementation

    def lifetime(self) -> Lifetime:
        return Lifetime.SINGLETON

    def requires(self) -> tuple[type, ...]:
        return ()

    def create(self, resolved: Mapping[type, object]) -> object:
        return self._implementation()


class ConstructorProvider(Provider):
    """A class built from the listed types, passed in that order.

    ``requires`` is the constructor's parameter list written out at the
    registration. A request-scoped requirement under a ``SINGLETON``
    lifetime is still a ``ScopeLeak`` at startup: the check reads this
    tuple like any other provider's.
    """

    def __init__(
        self,
        implementation: type,
        lifetime: Lifetime,
        requires: tuple[type, ...],
        provides: type | None = None,
    ) -> None:
        self._implementation = implementation
        self._lifetime = lifetime
        self._requires = requires
        self._provides = implementation if provides is None else provides

    def provides(self) -> type:
        return self._provides

    def lifetime(self) -> Lifetime:
        return self._lifetime

    def requires(self) -> tuple[type, ...]:
        return self._requires

    def create(self, resolved: Mapping[type, object]) -> object:
        return self._implementation(*(resolved[item] for item in self._requires))


class ServiceProvider(ConstructorProvider):
    """An ``ApplicationService`` from its prepare, execute and finalise types.

    Request-scoped, because its execute handler holds the request's unit of
    work. The three handler types are the registration's only requirements.
    """

    def __init__(
        self,
        service: type,
        prepare: type,
        execute: type,
        finalise: type,
    ) -> None:
        super().__init__(service, Lifetime.REQUEST, (prepare, execute, finalise))
