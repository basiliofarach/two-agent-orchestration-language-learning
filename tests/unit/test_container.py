"""The application container registers the request path and validates itself."""

import base64
from collections.abc import Mapping
from uuid import UUID

import pytest
from pydantic import SecretStr, ValidationError
from tests.support.repository import RepositoryPaths

from tutor_api.container import ApplicationContainer, SettingsProvider
from tutor_api.di.container import Container, RequestScope
from tutor_api.di.lifetime import Lifetime, UnregisteredDependency
from tutor_api.routers.health import HealthStatus
from tutor_api.settings import ApplicationSettings
from tutor_core.application.agents.generation import GenerationAgent
from tutor_core.application.agents.retrieval import RetrievalAgent
from tutor_core.application.services.conduct_turn import (
    ConductTurn,
    ExecuteTurn,
    FinaliseTurn,
    PrepareTurn,
)
from tutor_core.application.turn.guarded_generation import GenerationGuard
from tutor_core.application.turn.guarded_retrieval import RetrievalGuard
from tutor_core.application.turn.orchestrator import TurnOrchestrator
from tutor_core.application.turn.record import TurnRecordBuilder
from tutor_core.domain.gates.conflict import ConflictAmbiguityGate
from tutor_core.domain.gates.context_permission import ContextPermissionGate
from tutor_core.domain.gates.drift import DriftAnomalyGate
from tutor_core.domain.gates.sensitivity import SensitivityHighStakesGate
from tutor_core.domain.models.learner import HistoryFieldSet
from tutor_core.domain.ports.audit_sink import AuditSinkPort
from tutor_core.domain.ports.cipher import CipherPort
from tutor_core.domain.ports.clock import ClockPort
from tutor_core.domain.ports.corpus_ingestion import CorpusIngestionPort
from tutor_core.domain.ports.embedding import EmbeddingPort
from tutor_core.domain.ports.grammar_check import GrammarCheckPort
from tutor_core.domain.ports.knowledge_base import KnowledgeBasePort
from tutor_core.domain.ports.language_model import LanguageModelPort
from tutor_core.domain.ports.learner_history import LearnerHistoryPort
from tutor_core.domain.ports.pii_redaction import PiiRedactionPort
from tutor_core.domain.ports.policy_artifact import PolicyArtifactPort
from tutor_core.domain.ports.policy_publication import PolicyPublicationPort
from tutor_core.domain.ports.prompt_template import PromptTemplatePort
from tutor_core.domain.ports.safety_classifier import SafetyClassifierPort
from tutor_core.domain.ports.source_support import SourceSupportPort
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
            "postgres_user": "tutor_owner",
            "postgres_db": "tutor",
            "postgres_app_password": "app-secret",
            "tutor_kek": SecretStr(base64.b64encode(bytes(range(32))).decode()),
            "tutor_kek_id": UUID(int=1),
            "model_pin_path": RepositoryPaths().root() / "config" / "runtime.toml",
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


class TestTurnPathRegistration:
    def _scope(self) -> RequestScope:
        return (
            Configured()
            .container(
                history_fields="proficiency_level,events",
                conflict_confidence_threshold=0.5,
            )
            .scope()
        )

    @pytest.mark.parametrize(
        "port",
        [
            LearnerHistoryPort,
            ContextPermissionGate,
            ConflictAmbiguityGate,
            RetrievalAgent,
            RetrievalGuard,
            PromptTemplatePort,
            LanguageModelPort,
            GrammarCheckPort,
            SafetyClassifierPort,
            SourceSupportPort,
            GenerationAgent,
            GenerationGuard,
            SensitivityHighStakesGate,
            DriftAnomalyGate,
            TurnOrchestrator,
            TurnRecordBuilder,
            PrepareTurn,
            ExecuteTurn,
            FinaliseTurn,
            ConductTurn,
        ],
    )
    def test_the_turn_path_resolves(self, port: type) -> None:
        scope = self._scope()
        assert isinstance(scope.resolve(port), port)

    def test_an_unset_history_allowlist_is_refused(self) -> None:
        with pytest.raises(ValueError, match="HISTORY_FIELDS"):
            Configured().container().scope().resolve(LearnerHistoryPort)

    def test_an_unset_model_pin_is_refused(self) -> None:
        container = Configured().container(model_pin_path=None)
        with pytest.raises(ValueError, match="MODEL_PIN_PATH"):
            container.resolve(LanguageModelPort)

    def test_the_gate_and_the_history_read_share_one_field_set(self) -> None:
        scope = self._scope()
        assert scope.resolve(HistoryFieldSet) is scope.resolve(HistoryFieldSet)
        assert scope.resolve(HistoryFieldSet) == HistoryFieldSet(
            fields=("proficiency_level", "events")
        )

    def test_an_unset_conflict_threshold_is_refused(self) -> None:
        container = Configured().container(history_fields="proficiency_level")
        with pytest.raises(ValueError, match="CONFLICT_CONFIDENCE_THRESHOLD"):
            container.scope().resolve(ConflictAmbiguityGate)


class TestHealthStatus:
    def test_rejects_an_undeclared_field(self) -> None:
        with pytest.raises(ValidationError):
            HealthStatus(status="ok", database_configured=True, leaked="secret")

    def test_is_frozen(self) -> None:
        status = HealthStatus(status="ok", database_configured=True)
        with pytest.raises(ValidationError):
            status.status = "degraded"
