"""The container resolves by type and keeps singletons on the instance."""

import pytest
from tests.unit.di.test_lifetime_validation import (
    GenerationAgent,
    LearnerHistory,
    PolicyCard,
    StubProvider,
)

from tutor_api.di.container import Container
from tutor_api.di.lifetime import Lifetime, ScopeLeak, UnregisteredDependency


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
