"""The container resolves by type and keeps singletons on the instance."""

import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor

import pytest
from tests.unit.di.test_lifetime_validation import (
    GenerationAgent,
    LearnerHistory,
    PolicyCard,
    StubProvider,
)

from tutor_api.di.container import Container
from tutor_api.di.lifetime import (
    Lifetime,
    ScopeClosed,
    ScopeLeak,
    UnregisteredDependency,
)


class TestContainer:
    def test_resolves_a_registered_type(self) -> None:
        container = Container((StubProvider(PolicyCard, Lifetime.SINGLETON),))
        assert isinstance(container.resolve(PolicyCard), PolicyCard)

    def test_a_singleton_is_built_once(self) -> None:
        container = Container((StubProvider(PolicyCard, Lifetime.SINGLETON),))
        assert container.resolve(PolicyCard) is container.resolve(PolicyCard)

    def test_request_scoped_is_built_each_time(self) -> None:
        container = Container((StubProvider(LearnerHistory, Lifetime.REQUEST),))
        assert container.resolve(LearnerHistory) is not container.resolve(
            LearnerHistory
        )

    def test_requirements_are_resolved_first(self) -> None:
        container = Container(
            (
                StubProvider(PolicyCard, Lifetime.SINGLETON),
                StubProvider(GenerationAgent, Lifetime.SINGLETON, (PolicyCard,)),
            )
        )
        assert isinstance(container.resolve(GenerationAgent), GenerationAgent)

    def test_an_unregistered_type_is_refused(self) -> None:
        with pytest.raises(UnregisteredDependency):
            Container(()).resolve(PolicyCard)

    def test_two_containers_share_no_singleton(self) -> None:
        """Instance state, not module state: two apps in one process differ."""
        providers = (StubProvider(PolicyCard, Lifetime.SINGLETON),)
        assert Container(providers).resolve(PolicyCard) is not Container(
            providers
        ).resolve(PolicyCard)

    def test_validate_refuses_a_leaking_graph(self) -> None:
        container = Container(
            (
                StubProvider(LearnerHistory, Lifetime.REQUEST),
                StubProvider(GenerationAgent, Lifetime.SINGLETON, (LearnerHistory,)),
            )
        )
        with pytest.raises(ScopeLeak):
            container.validate()


class SlowProvider(StubProvider):
    """Widens the window between the cache check and the store."""

    def __init__(self, provided: type, lifetime: Lifetime) -> None:
        super().__init__(provided, lifetime)
        self.created = 0

    def create(self, resolved: Mapping[type, object]) -> object:
        self.created += 1
        time.sleep(0.01)
        return self._provided()


class TestConcurrentResolution:
    def test_a_singleton_is_built_once_under_concurrency(self) -> None:
        """``Provide`` is synchronous, so FastAPI resolves in worker threads.

        Unsynchronised, both threads miss the cache and both construct; one
        instance is then discarded, which for a singleton holding an engine
        or a pool would leak it.
        """
        provider = SlowProvider(PolicyCard, Lifetime.SINGLETON)
        container = Container((provider,))
        with ThreadPoolExecutor(max_workers=8) as pool:
            resolved = list(pool.map(lambda _: container.resolve(PolicyCard), range(8)))
        assert provider.created == 1
        assert len({id(item) for item in resolved}) == 1


class Connection:
    """Stands in for the request's enlisted connection."""


class Holder:
    """A request-scoped consumer that keeps what it was handed."""

    def __init__(self, connection: object) -> None:
        self.connection = connection


class HolderProvider(StubProvider):
    def __init__(self, provided: type) -> None:
        super().__init__(provided, Lifetime.REQUEST, (Connection,))

    def create(self, resolved: Mapping[type, object]) -> object:
        return Holder(resolved[Connection])


class KnowledgeHolder(Holder):
    pass


class AuditHolder(Holder):
    pass


class TestRequestScope:
    def _container(self) -> Container:
        return Container(
            (
                StubProvider(Connection, Lifetime.REQUEST),
                StubProvider(PolicyCard, Lifetime.SINGLETON),
                HolderProvider(KnowledgeHolder),
                HolderProvider(AuditHolder),
            )
        )

    def test_a_request_object_is_built_once_per_scope(self) -> None:
        scope = self._container().scope()
        assert scope.resolve(Connection) is scope.resolve(Connection)

    def test_two_consumers_in_one_scope_share_the_connection(self) -> None:
        """Retrieval and the audit sink must enlist in one transaction."""
        scope = self._container().scope()
        knowledge = scope.resolve(KnowledgeHolder)
        audit = scope.resolve(AuditHolder)
        assert isinstance(knowledge, Holder)
        assert isinstance(audit, Holder)
        assert knowledge.connection is audit.connection
        assert knowledge.connection is scope.resolve(Connection)

    def test_two_scopes_share_no_request_object(self) -> None:
        """One learner's request never sees another's connection."""
        container = self._container()
        assert container.scope().resolve(Connection) is not container.scope().resolve(
            Connection
        )

    def test_a_singleton_is_shared_across_scopes(self) -> None:
        container = self._container()
        assert container.scope().resolve(PolicyCard) is container.resolve(PolicyCard)

    def test_an_unregistered_type_is_refused_in_a_scope(self) -> None:
        with pytest.raises(UnregisteredDependency):
            Container(()).scope().resolve(PolicyCard)

    def test_one_request_reuses_the_request_scoped_instance(self) -> None:
        scope = self._container().scope()
        assert scope.resolve(Connection) is scope.resolve(Connection)

    def test_the_next_request_gets_a_new_instance(self) -> None:
        container = self._container()
        assert container.scope().resolve(Connection) is not container.scope().resolve(
            Connection
        )

    def test_closing_the_scope_drops_the_cache(self) -> None:
        container = self._container()
        scope = container.scope()
        first = scope.resolve(Connection)
        scope.close()
        with pytest.raises(ScopeClosed):
            scope.resolve(Connection)
        assert container.scope().resolve(Connection) is not first
