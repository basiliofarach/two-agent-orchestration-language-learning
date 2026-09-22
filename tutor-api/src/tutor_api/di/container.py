"""Resolve the object graph, and refuse to start one that can leak."""

from tutor_api.di.lifetime import Lifetime, ScopeLeak, UnregisteredDependency
from tutor_api.di.provider import Provider


class LifetimeValidation:
    """Reject a graph in which a singleton captures request-scoped state.

    This is the control DEC-0003 attributed to wireup and DEC-0013 keeps by
    owning it. A ``ContentGenerationAgent`` registered as a singleton that
    retained a ``LearnerHistoryPort`` bound to one learner's session would
    serve one minor's history into another's request. The check runs before
    the application accepts traffic, so the failure is a refusal to boot.

    FastAPI cannot do this: ``Depends()`` resolves per call and has no view of
    how long the object on the other side lives.
    """

    def __init__(self, providers: tuple[Provider, ...]) -> None:
        self._providers = providers

    def validate(self) -> None:
        """Raise on the first unresolvable or scope-leaking registration."""
        lifetimes = {
            provider.provides(): provider.lifetime() for provider in self._providers
        }
        for provider in self._providers:
            holder = provider.provides()
            for required in provider.requires():
                if required not in lifetimes:
                    raise UnregisteredDependency(holder, required)
                if (
                    provider.lifetime() is Lifetime.SINGLETON
                    and lifetimes[required] is Lifetime.REQUEST
                ):
                    raise ScopeLeak(holder, required)


class Container:
    """The object graph. Constructed once per application, never at import."""

    def __init__(self, providers: tuple[Provider, ...]) -> None:
        self._providers = {provider.provides(): provider for provider in providers}
        self._singletons: dict[type, object] = {}

    def validate(self) -> None:
        """Check every registration before the application serves traffic."""
        LifetimeValidation(tuple(self._providers.values())).validate()

    def resolve(self, requested: type) -> object:
        """Return the object registered for ``requested``.

        A singleton is built once and kept on this container — on the
        instance, never at module level, so two applications in one process
        (the test suite runs several) share nothing.
        """
        if requested in self._singletons:
            return self._singletons[requested]
        provider = self._providers.get(requested)
        if provider is None:
            raise UnregisteredDependency(Container, requested)
        created = provider.create(
            {required: self.resolve(required) for required in provider.requires()}
        )
        if provider.lifetime() is Lifetime.SINGLETON:
            self._singletons[requested] = created
        return created
