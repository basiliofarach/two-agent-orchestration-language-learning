"""The scope-leak control: a singleton may not capture request-scoped state."""

from collections.abc import Mapping

import pytest

from tutor_api.di.container import LifetimeValidation
from tutor_api.di.lifetime import Lifetime, ScopeLeak, UnregisteredDependency
from tutor_api.di.provider import Provider


class LearnerHistory:
    """Stands in for a collaborator bound to one learner's session."""


class PolicyCard:
    """Stands in for a collaborator holding no learner data."""


class GenerationAgent:
    """Stands in for the singleton DEC-0013 names as the hazard."""


class StubProvider(Provider):
    def __init__(
        self,
        provided: type,
        lifetime: Lifetime,
        requires: tuple[type, ...] = (),
    ) -> None:
        self._provided = provided
        self._lifetime = lifetime
        self._requires = requires

    def provides(self) -> type:
        return self._provided

    def lifetime(self) -> Lifetime:
        return self._lifetime

    def requires(self) -> tuple[type, ...]:
        return self._requires

    def create(self, resolved: Mapping[type, object]) -> object:
        return self._provided()


class TestProviderIsAbstract:
    def test_a_provider_missing_a_method_cannot_be_instantiated(self) -> None:
        class Incomplete(Provider):
            def provides(self) -> type:
                return object

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]


class TestLifetimeValidation:
    def test_singleton_capturing_request_state_is_refused(self) -> None:
        providers = (
            StubProvider(LearnerHistory, Lifetime.REQUEST),
            StubProvider(GenerationAgent, Lifetime.SINGLETON, (LearnerHistory,)),
        )
        with pytest.raises(ScopeLeak, match="serves one learner's data"):
            LifetimeValidation(providers).validate()

    def test_singleton_on_singleton_is_allowed(self) -> None:
        providers = (
            StubProvider(PolicyCard, Lifetime.SINGLETON),
            StubProvider(GenerationAgent, Lifetime.SINGLETON, (PolicyCard,)),
        )
        LifetimeValidation(providers).validate()

    def test_request_scoped_may_depend_on_either(self) -> None:
        providers = (
            StubProvider(PolicyCard, Lifetime.SINGLETON),
            StubProvider(LearnerHistory, Lifetime.REQUEST),
            StubProvider(
                GenerationAgent, Lifetime.REQUEST, (PolicyCard, LearnerHistory)
            ),
        )
        LifetimeValidation(providers).validate()

    def test_unregistered_requirement_is_refused(self) -> None:
        providers = (
            StubProvider(GenerationAgent, Lifetime.SINGLETON, (LearnerHistory,)),
        )
        with pytest.raises(UnregisteredDependency, match="no provider registers"):
            LifetimeValidation(providers).validate()

    def test_an_empty_graph_validates(self) -> None:
        LifetimeValidation(()).validate()

    def test_the_message_names_both_sides(self) -> None:
        providers = (
            StubProvider(LearnerHistory, Lifetime.REQUEST),
            StubProvider(GenerationAgent, Lifetime.SINGLETON, (LearnerHistory,)),
        )
        with pytest.raises(ScopeLeak) as raised:
            LifetimeValidation(providers).validate()
        assert "GenerationAgent" in str(raised.value)
        assert "LearnerHistory" in str(raised.value)
