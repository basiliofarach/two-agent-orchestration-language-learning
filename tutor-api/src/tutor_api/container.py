"""Registration — the only site that names concrete classes (rule 3).

Providers live here rather than as decorators on implementations. A class that
reaches for its own container is not injected, it is coupled, and the
capability-scoping argument in DEC-0001 rests on a collaborator holding only
what it was handed.
"""

from collections.abc import Mapping

from tutor_api.di.container import Container
from tutor_api.di.lifetime import Lifetime
from tutor_api.di.provider import Provider
from tutor_api.settings import ApplicationSettings


class SettingsProvider(Provider):
    """Configuration, read once for the process.

    A singleton because configuration is process-wide and holds no learner
    data. The model remains mutable; its lifetime and mutability are separate
    concerns.
    """

    def provides(self) -> type:
        return ApplicationSettings

    def lifetime(self) -> Lifetime:
        return Lifetime.SINGLETON

    def requires(self) -> tuple[type, ...]:
        return ()

    def create(self, resolved: Mapping[type, object]) -> object:
        return ApplicationSettings()


class ApplicationContainer:
    """Build the object graph. Nothing is constructed at import."""

    def build(self) -> Container:
        """Return a validated container. An invalid graph never starts."""
        container = Container(self._providers())
        container.validate()
        return container

    def _providers(self) -> tuple[Provider, ...]:
        return (SettingsProvider(),)
