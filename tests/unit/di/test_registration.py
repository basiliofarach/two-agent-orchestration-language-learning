"""The base providers keep the lifetime check honest (DEC-0013)."""

import pytest

from tutor_api.di.container import Container
from tutor_api.di.lifetime import Lifetime, RegistrationCycle, ScopeLeak
from tutor_api.di.registration import (
    ConstructorProvider,
    ServiceProvider,
    StatelessProvider,
)


class Learner:
    """Request-scoped: one learner's data."""


class Pair:
    """Holds two collaborators, in constructor order."""

    def __init__(self, first: object, second: object) -> None:
        self.first = first
        self.second = second


class Port:
    """An abstract type a registration provides."""


class Stateless:
    """No constructor arguments."""


class TestStatelessProvider:
    def test_it_builds_one_shared_instance(self) -> None:
        container = Container((StatelessProvider(Stateless),))
        container.validate()
        assert container.resolve(Stateless) is container.resolve(Stateless)


class TestConstructorProvider:
    def test_requirements_are_passed_in_the_written_order(self) -> None:
        container = Container(
            (
                StatelessProvider(Stateless),
                ConstructorProvider(Learner, Lifetime.REQUEST, ()),
                ConstructorProvider(Pair, Lifetime.REQUEST, (Learner, Stateless)),
            )
        )
        built = container.resolve(Pair)
        assert isinstance(built, Pair)
        assert isinstance(built.first, Learner)
        assert isinstance(built.second, Stateless)

    def test_it_can_provide_an_abstract_type(self) -> None:
        provider = ConstructorProvider(Stateless, Lifetime.SINGLETON, (), provides=Port)
        assert provider.provides() is Port

    def test_a_singleton_requiring_request_state_refuses_to_boot(self) -> None:
        container = Container(
            (
                ConstructorProvider(Learner, Lifetime.REQUEST, ()),
                StatelessProvider(Stateless),
                ConstructorProvider(Pair, Lifetime.SINGLETON, (Learner, Stateless)),
            )
        )
        with pytest.raises(ScopeLeak):
            container.validate()


class TestServiceProvider:
    def test_a_service_is_request_scoped_and_needs_its_three_stages(self) -> None:
        provider = ServiceProvider(Pair, Stateless, Learner, Port)
        assert provider.lifetime() is Lifetime.REQUEST
        assert provider.requires() == (Stateless, Learner, Port)


class TestResolutionCycle:
    def test_a_cycle_resolved_without_validation_still_raises(self) -> None:
        container = Container(
            (
                ConstructorProvider(Pair, Lifetime.REQUEST, (Learner, Stateless)),
                ConstructorProvider(Learner, Lifetime.REQUEST, (Pair,)),
                StatelessProvider(Stateless),
            )
        )
        with pytest.raises(RegistrationCycle):
            container.resolve(Pair)
