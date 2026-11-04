"""The real application over one test database, with the model stubbed.

Everything but the language model is the production graph: container,
router, LangGraph orchestrator, the four gates, Postgres adapters. The model
is stubbed for determinism, not to avoid the integration (rule 7). The
database is seeded by the production operator seed.
"""

import base64
from collections.abc import Mapping
from uuid import UUID

from pydantic import SecretStr

from tests.integration.test_request_transaction import ApplicationLogin
from tests.support.migrated_database import MigratedDatabase, PostgresUrl
from tests.support.repository import RepositoryPaths
from tests.unit.test_container import FixedSettings
from tutor_api.adapters.persistence.database import DatabaseEngine
from tutor_api.container import ApplicationContainer
from tutor_api.curation.prototype_seed import PrototypePlan, PrototypeSeed, SeedPlan
from tutor_api.di.container import Container
from tutor_api.di.lifetime import Lifetime
from tutor_api.di.provider import Provider
from tutor_api.settings import ApplicationSettings
from tutor_core.domain.ports.language_model import LanguageModelPort

KEK = bytes(range(32))
THRESHOLD = 0.3


class StubModelProvider(Provider):
    """Registers a given model in place of the pinned Ollama adapter."""

    def __init__(self, model: LanguageModelPort) -> None:
        self._model = model

    def provides(self) -> type:
        return LanguageModelPort

    def lifetime(self) -> Lifetime:
        return Lifetime.SINGLETON

    def requires(self) -> tuple[type, ...]:
        return ()

    def create(self, resolved: Mapping[type, object]) -> object:
        return self._model


class TurnApp:
    """Migrate, enable the application login, seed, and build the container."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._login = ApplicationLogin(url)

    def settings(self) -> ApplicationSettings:
        return ApplicationSettings(
            _env_file=None,  # type: ignore[call-arg]
            postgres_app_user=self._login.role(),
            database_url=self._url,
            application_database_url=self._login.async_url(),
            tutor_kek=SecretStr(base64.b64encode(KEK).decode()),
            tutor_kek_id=UUID(int=1),
            history_fields="proficiency_level,events",
            conflict_confidence_threshold=THRESHOLD,
            model_pin_path=RepositoryPaths().root() / "config" / "runtime.toml",
            # No run directory: a test that wants one passes its own.
            simulation_reports_dir=RepositoryPaths().root() / "tests" / "no-runs",
        )

    def container(self, model: LanguageModelPort) -> Container:
        providers = tuple(
            provider
            for provider in ApplicationContainer(
                FixedSettings(self.settings())
            ).providers()
            if provider.provides() is not LanguageModelPort
        )
        container = Container((*providers, StubModelProvider(model)))
        container.validate()
        return container

    async def install(
        self, container: Container, plan: SeedPlan | None = None
    ) -> SeedPlan:
        MigratedDatabase().upgrade(self._url)
        self._login.enable()
        engine = DatabaseEngine(PostgresUrl(self._url).async_url())
        try:
            return await PrototypeSeed(engine, container).run(
                plan if plan is not None else PrototypePlan().plan(THRESHOLD)
            )
        finally:
            await engine.dispose()


class GrammarPlan:
    """The prototype plan with an English-grammar document in place of greetings.

    The REQ-EVAL catalogue asks about the present simple (DEC-0015). Over
    the Spanish-greetings document every in-scope case would retrieve
    nothing relevant and halt at the conflict gate, so the scenario run is
    seeded with material the cases can be grounded in. Everything else —
    card, learner, history, threshold — is the prototype plan's.
    """

    def plan(self) -> SeedPlan:
        return (
            PrototypePlan()
            .plan(THRESHOLD)
            .model_copy(
                update={
                    "document_uri": "kb://english/present-simple",
                    "document_content": "\n\n".join(
                        (
                            "The present simple describes habits and general facts.",
                            "Use the present simple for routines: I walk to school.",
                            "Use the present simple for general truths: Water boils "
                            "at 100 degrees.",
                            "In the present simple, add -s for he, she and it: "
                            "she walks.",
                        )
                    ),
                }
            )
        )
