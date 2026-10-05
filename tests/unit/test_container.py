"""The application container registers the request path and validates itself."""

import base64
from collections.abc import Mapping
from uuid import UUID

import pytest
from pydantic import SecretStr, ValidationError

from tutor_api.container import ApplicationContainer, SettingsProvider
from tutor_api.di.container import Container
from tutor_api.di.lifetime import Lifetime, UnregisteredDependency
from tutor_api.routers.health import HealthStatus
from tutor_api.settings import ApplicationSettings
from tutor_core.domain.ports.audit_sink import AuditSinkPort
from tutor_core.domain.ports.cipher import CipherPort
from tutor_core.domain.ports.clock import ClockPort
from tutor_core.domain.ports.corpus_ingestion import CorpusIngestionPort
from tutor_core.domain.ports.embedding import EmbeddingPort
from tutor_core.domain.ports.knowledge_base import KnowledgeBasePort
from tutor_core.domain.ports.pii_redaction import PiiRedactionPort
from tutor_core.domain.ports.policy_artifact import PolicyArtifactPort
from tutor_core.domain.ports.policy_publication import PolicyPublicationPort
from tutor_core.domain.ports.unit_of_work import TransactionConnection, UnitOfWorkPort


class FixedSettings(SettingsProvider):
    """Settings handed in, so no test reads the developer's environment."""

    def __init__(self, settings: ApplicationSettings) -> None:
        self._settings = settings

    def create(self, resolved: Mapping[type, object]) -> object:
        return self._settings


class Configured:
    """A container over settings a test controls."""

    def settings(self, **values: object) -> ApplicationSettings:
        defaults: dict[str, object] = {
            "postgres_db": "tutor",
            "postgres_app_password": "app-secret",
            "tutor_kek": SecretStr(base64.b64encode(bytes(range(32))).decode()),
            "tutor_kek_id": UUID(int=1),
        }
        return ApplicationSettings(_env_file=None, **{**defaults, **values})  # type: ignore[arg-type]

    def container(self, **values: object) -> Container:
        return ApplicationContainer(FixedSettings(self.settings(**values))).build()


class TestSettingsProvider:
    def test_provides_the_settings_type(self) -> None:
        assert SettingsProvider().provides() is ApplicationSettings

    def test_is_a_singleton_because_configuration_is_process_wide(self) -> None:
        assert SettingsProvider().lifetime() is Lifetime.SINGLETON

    def test_requires_nothing(self) -> None:
        assert SettingsProvider().requires() == ()

    def test_creates_settings(self) -> None:
        assert isinstance(SettingsProvider().create({}), ApplicationSettings)


class TestApplicationContainer:
    def test_resolves_database_settings(self) -> None:
        container = Configured().container()
        assert isinstance(container.resolve(ApplicationSettings), ApplicationSettings)

    def test_settings_are_read_once(self) -> None:
        container = Configured().container()
        assert container.resolve(ApplicationSettings) is container.resolve(
            ApplicationSettings
        )

    def test_build_validates_the_graph(self) -> None:
        """An invalid graph must fail here, not on the first request."""
        assert Configured().container() is not None

    def test_build_returns_a_new_container_each_time(self) -> None:
        """No module-level container: two builds share no state (rule 3)."""
        assert Configured().container() is not Configured().container()


class TestRequestPathRegistration:
    @pytest.mark.parametrize(
        "port",
        [
            ClockPort,
            CipherPort,
            EmbeddingPort,
            PiiRedactionPort,
            KnowledgeBasePort,
            PolicyArtifactPort,
            AuditSinkPort,
            UnitOfWorkPort,
            TransactionConnection,
        ],
    )
    def test_the_request_path_resolves(self, port: type) -> None:
        assert isinstance(Configured().container().scope().resolve(port), port)

    @pytest.mark.parametrize("port", [CorpusIngestionPort, PolicyPublicationPort])
    def test_curation_is_not_a_request_capability(self, port: type) -> None:
        """The tutoring path cannot ingest a document or publish a policy."""
        with pytest.raises(UnregisteredDependency):
            Configured().container().scope().resolve(port)

    def test_one_request_holds_one_connection(self) -> None:
        scope = Configured().container().scope()
        assert scope.resolve(TransactionConnection) is scope.resolve(
            TransactionConnection
        )

    def test_two_requests_hold_two_connections(self) -> None:
        container = Configured().container()
        assert container.scope().resolve(
            TransactionConnection
        ) is not container.scope().resolve(TransactionConnection)

    @pytest.mark.parametrize(
        "port",
        [KnowledgeBasePort, PolicyArtifactPort, AuditSinkPort, UnitOfWorkPort],
    )
    def test_connection_holders_are_request_scoped(self, port: type) -> None:
        """A singleton holding the connection would share it across learners."""
        providers = {
            provider.provides(): provider
            for provider in ApplicationContainer(
                FixedSettings(Configured().settings())
            ).providers()
        }
        assert providers[port].lifetime() is Lifetime.REQUEST
        assert TransactionConnection in providers[port].requires()

    def test_a_missing_kek_names_what_to_set(self) -> None:
        container = Configured().container(tutor_kek=None)
        with pytest.raises(ValueError, match="TUTOR_KEK"):
            container.resolve(CipherPort)

    def test_a_kek_that_is_not_base64_is_refused(self) -> None:
        container = Configured().container(tutor_kek=SecretStr("not base64!"))
        with pytest.raises(ValueError, match="base64"):
            container.resolve(CipherPort)

    def test_the_cipher_round_trips_with_the_injected_kek(self) -> None:
        cipher = Configured().container().resolve(CipherPort)
        assert isinstance(cipher, CipherPort)
        assert cipher.decrypt(cipher.encrypt(b"hola")) == b"hola"


class TestHealthStatus:
    def test_rejects_an_undeclared_field(self) -> None:
        with pytest.raises(ValidationError):
            HealthStatus(status="ok", database_configured=True, leaked="secret")

    def test_is_frozen(self) -> None:
        status = HealthStatus(status="ok", database_configured=True)
        with pytest.raises(ValidationError):
            status.status = "degraded"
