"""Resolve the object graph, and refuse to start one that can leak."""

from collections.abc import Callable
from threading import RLock

from tutor_api.di.lifetime import (
    DuplicateRegistration,
    Lifetime,
    RegistrationCycle,
    ScopeClosed,
    ScopeLeak,
    UnregisteredDependency,
)
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
        """Raise on a duplicate, a cycle, an unresolvable edge, or a leak."""
        self._reject_duplicates()
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
        CycleSearch(
            {provider.provides(): provider.requires() for provider in self._providers},
            set(lifetimes),
        ).walk_all()

    def _reject_duplicates(self) -> None:
        seen: set[type] = set()
        for provider in self._providers:
            provided = provider.provides()
            if provided in seen:
                raise DuplicateRegistration(provided)
            seen.add(provided)


class CycleSearch:
    """Name the types on a registration loop (BE-22a)."""

    def __init__(
        self,
        requires: dict[type, tuple[type, ...]],
        known: set[type],
    ) -> None:
        self._requires = requires
        self._known = known
        self._visiting: list[type] = []
        self._visited: set[type] = set()

    def walk_all(self) -> None:
        """Raise ``RegistrationCycle`` when a provider requires itself."""
        for node in tuple(self._known):
            self._walk(node)

    def _walk(self, node: type) -> None:
        if node in self._visited or node not in self._known:
            return
        if node in self._visiting:
            start = self._visiting.index(node)
            raise RegistrationCycle((*self._visiting[start:], node))
        self._visiting.append(node)
        for required in self._requires[node]:
            self._walk(required)
        self._visiting.pop()
        self._visited.add(node)


class RequestScope:
    """One request's ``REQUEST``-lifetime objects (DEC-0014).

    Within a scope a request-scoped type is built once, so the knowledge
    base, the audit sink and the unit of work a request resolves all hold
    the same connection, and retrieval commits with the audit row that
    describes it (DEC-0006). Two scopes share nothing request-scoped: one
    learner's request never receives another's connection. Singletons
    still come from the container.

    ``close`` drops the cache. Services have no ``dispose``: the scope is
    the request, and the next request opens another scope.
    """

    def __init__(self, build: Callable[[type, dict[type, object]], object]) -> None:
        self._build = build
        self._instances: dict[type, object] = {}
        self._closed = False

    def resolve(self, requested: type) -> object:
        """Return ``requested``, built at most once in this scope."""
        if self._closed:
            raise ScopeClosed
        return self._build(requested, self._instances)

    def close(self) -> None:
        """Drop every request-scoped instance this scope built."""
        self._instances.clear()
        self._closed = True


class Container:
    """The object graph. Constructed once per application, never at import."""

    def __init__(self, providers: tuple[Provider, ...]) -> None:
        self._registered = providers
        self._providers = {provider.provides(): provider for provider in providers}
        self._singletons: dict[type, object] = {}
        # `Provide.__call__` is synchronous, so FastAPI runs it in a worker
        # thread and two first requests can resolve concurrently. Without this
        # the check-build-store below is a race: both threads miss the cache,
        # both construct, and one instance is discarded — which for a
        # singleton holding an engine or a pool would leak it. Re-entrant
        # because `resolve` recurses through `requires()`.
        self._lock = RLock()

    def validate(self) -> None:
        """Check every registration before the application serves traffic."""
        LifetimeValidation(self._registered).validate()

    def resolve(self, requested: type) -> object:
        """Return the object registered for ``requested``.

        A singleton is built once and kept on this container — on the
        instance, never at module level, so two applications in one process
        (the test suite runs several) share nothing. Outside a scope a
        request-scoped type is built fresh on every call; use ``scope()``
        when collaborators must share one.
        """
        return self._build(requested, {})

    def scope(self) -> RequestScope:
        """Open the scope one HTTP request resolves from."""
        return RequestScope(self._build)

    def _build(
        self,
        requested: type,
        scoped: dict[type, object],
        stack: tuple[type, ...] = (),
    ) -> object:
        with self._lock:
            if requested in stack:
                raise RegistrationCycle((*stack, requested))
            if requested in self._singletons:
                return self._singletons[requested]
            if requested in scoped:
                return scoped[requested]
            provider = self._providers.get(requested)
            if provider is None:
                raise UnregisteredDependency(Container, requested)
            created = provider.create(
                {
                    required: self._build(required, scoped, (*stack, requested))
                    for required in provider.requires()
                }
            )
            if provider.lifetime() is Lifetime.SINGLETON:
                self._singletons[requested] = created
            else:
                scoped[requested] = created
            return created
