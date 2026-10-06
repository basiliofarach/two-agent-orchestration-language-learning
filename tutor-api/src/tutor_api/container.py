"""Registration — the only site that names concrete classes (rule 3).

Providers live here rather than as decorators on implementations. A class that
reaches for its own container is not injected, it is coupled, and the
capability-scoping argument in DEC-0001 rests on a collaborator holding only
what it was handed.

The request path is registered end to end: the ConductTurn use case and its
three stage handlers, the LangGraph orchestrator, the four gates, both agents,
redaction, retrieval, history, the session check, the fixed template, the pinned
model, the three
output checks, the policy in force, the audit sink, and the one connection
they share (DEC-0014). Curation is not. ``CorpusIngestionPort`` and
``PolicyPublicationPort`` have no provider, so no request can ingest a
document or publish a policy version (DEC-0001).
"""

import base64
import binascii
from collections.abc import Mapping
from typing import cast

from tutor_api.adapters.checks.grammar import MinorGrammarPatterns, PatternGrammarCheck
from tutor_api.adapters.checks.pii_redaction import RegexPiiRedactor, StandardPiiSteps
from tutor_api.adapters.checks.safety import CategorySafetyClassifier, MinorSafetyRules
from tutor_api.adapters.checks.source_support import (
    SentenceSourceSupport,
    SentenceSplitter,
)
from tutor_api.adapters.llm.fixed_prompt import FixedPromptTemplate
from tutor_api.adapters.llm.local_embedding import LocalEmbedding
from tutor_api.adapters.llm.ollama import (
    ModelfileWeights,
    ModelRevision,
    OllamaLanguageModel,
    PinnedModelName,
    PinnedRevision,
    UrllibOllamaEndpoint,
)
from tutor_api.adapters.persistence.aes_gcm_envelope import AesGcmEnvelope
from tutor_api.adapters.persistence.audit_query import (
    AuditRecordDecoder,
    PostgresAuditQuery,
)
from tutor_api.adapters.persistence.audit_sink import PostgresAuditSink
from tutor_api.adapters.persistence.cohort_report import PostgresCohortReport
from tutor_api.adapters.persistence.database import DatabaseEngine, RequestConnection
from tutor_api.adapters.persistence.database_url import ApplicationDatabaseUrl
from tutor_api.adapters.persistence.human_action import PostgresHumanAction
from tutor_api.adapters.persistence.knowledge_base import (
    CitedSources,
    CosineConfidence,
    PgVectorKnowledgeBase,
    VectorLiteral,
)
from tutor_api.adapters.persistence.learner_history import (
    HistoryOutcomeCodec,
    PostgresLearnerHistory,
)
from tutor_api.adapters.persistence.schema import BaseSchema
from tutor_api.adapters.persistence.sealed import SealedValue
from tutor_api.adapters.persistence.session_directory import PostgresSessionDirectory
from tutor_api.adapters.persistence.tutoring_session import PostgresTutoringSession
from tutor_api.adapters.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tutor_api.adapters.persistence.versioned_policy import (
    PolicyCardCodec,
    VersionedPolicyCard,
)
from tutor_api.adapters.system_clock import SystemClock
from tutor_api.di.container import Container
from tutor_api.di.lifetime import Lifetime
from tutor_api.di.provider import Provider
from tutor_api.di.registration import (
    ConstructorProvider,
    ServiceProvider,
    StatelessProvider,
)
from tutor_api.prototype import PrototypeCopy
from tutor_api.settings import ApplicationSettings
from tutor_core.application.agents.generation import (
    ContentGenerationAgent,
    GenerationAgent,
)
from tutor_core.application.agents.retrieval import DataRetrievalAgent, RetrievalAgent
from tutor_core.application.services.conduct_turn import (
    ConductTurn,
    ExecuteTurn,
    FinaliseTurn,
    PrepareTurn,
)
from tutor_core.application.services.read_audit import (
    ExecuteAudit,
    ExecuteTurnRead,
    FinaliseAudit,
    FinaliseTurnRead,
    PrepareAudit,
    PrepareTurnRead,
    ReadAudit,
    ReadTurn,
)
from tutor_core.application.services.record_human_action import (
    ActionRules,
    ExecuteAction,
    FinaliseAction,
    PrepareAction,
    RecordHumanAction,
)
from tutor_core.application.services.replay_turn import (
    DraftComparison,
    ExecuteReplay,
    FinaliseReplay,
    PrepareReplay,
    ReplayTurn,
)
from tutor_core.application.services.report_cohort import (
    ExecuteCohort,
    FinaliseCohort,
    PrepareCohort,
    ReportCohort,
)
from tutor_core.application.services.session_surface import (
    ExecuteLearnerList,
    ExecuteOpenSession,
    ExecuteSession,
    ExecuteSessionList,
    ExecuteStream,
    FinaliseLearnerList,
    FinaliseSession,
    FinaliseSessionList,
    FinaliseStream,
    ListLearners,
    ListSessions,
    OpenSession,
    PrepareLearnerList,
    PrepareOpenSession,
    PrepareSession,
    PrepareSessionList,
    PrepareStream,
    ReadSession,
    SessionEvents,
    SseEncoder,
    StreamSession,
)
from tutor_core.application.turn.baseline import SessionBaselineCalculator
from tutor_core.application.turn.guarded_generation import (
    GenerateIfConsistent,
    GenerationGuard,
)
from tutor_core.application.turn.guarded_retrieval import (
    RetrievalGuard,
    RetrieveIfPermitted,
)
from tutor_core.application.turn.orchestrator import (
    LangGraphTurnOrchestrator,
    TurnNodes,
    TurnOrchestrator,
)
from tutor_core.application.turn.record import GateRows, TurnRecordBuilder
from tutor_core.domain.audit.chain import ChainVerifier
from tutor_core.domain.audit.context_digest import CitedContextDigest
from tutor_core.domain.audit.record_hash import ActionRecordHash, AuditRecordHash
from tutor_core.domain.gates.citation import VerdictCitation
from tutor_core.domain.gates.conflict import ConflictAmbiguityGate
from tutor_core.domain.gates.context_permission import ContextPermissionGate
from tutor_core.domain.gates.contradiction import SnippetContradiction
from tutor_core.domain.gates.drift import DriftAnomalyGate
from tutor_core.domain.gates.registry import GateRegistry
from tutor_core.domain.gates.sensitivity import SensitivityHighStakesGate
from tutor_core.domain.models.learner import HistoryFieldSet
from tutor_core.domain.policy.confidence import ConfidenceThreshold
from tutor_core.domain.policy.rule_lookup import PolicyRuleLookup
from tutor_core.domain.ports.audit_query import AuditQueryPort
from tutor_core.domain.ports.audit_sink import AuditSinkPort
from tutor_core.domain.ports.cipher import CipherPort
from tutor_core.domain.ports.clock import ClockPort
from tutor_core.domain.ports.cohort_report import CohortReportPort
from tutor_core.domain.ports.embedding import EmbeddingPort
from tutor_core.domain.ports.grammar_check import GrammarCheckPort
from tutor_core.domain.ports.human_action import HumanActionPort
from tutor_core.domain.ports.knowledge_base import KnowledgeBasePort
from tutor_core.domain.ports.language_model import LanguageModelPort
from tutor_core.domain.ports.learner_history import LearnerHistoryPort
from tutor_core.domain.ports.pii_redaction import PiiRedactionPort
from tutor_core.domain.ports.policy_artifact import PolicyArtifactPort
from tutor_core.domain.ports.prompt_template import PromptTemplatePort
from tutor_core.domain.ports.safety_classifier import SafetyClassifierPort
from tutor_core.domain.ports.session_directory import SessionDirectoryPort
from tutor_core.domain.ports.source_support import SourceSupportPort
from tutor_core.domain.ports.tutoring_session import TutoringSessionPort
from tutor_core.domain.ports.unit_of_work import TransactionConnection, UnitOfWorkPort


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


class CipherProvider(Provider):
    """The envelope cipher over the injected KEK (DEC-0012).

    A missing or malformed KEK raises on first resolution and names the
    variable to set. There is no fallback key.
    """

    def provides(self) -> type:
        return CipherPort

    def lifetime(self) -> Lifetime:
        return Lifetime.SINGLETON

    def requires(self) -> tuple[type, ...]:
        return (ApplicationSettings,)

    def create(self, resolved: Mapping[type, object]) -> object:
        settings = cast(ApplicationSettings, resolved[ApplicationSettings])
        if settings.tutor_kek is None or settings.tutor_kek_id is None:
            msg = "TUTOR_KEK and TUTOR_KEK_ID are not set. Export them."
            raise ValueError(msg)
        return AesGcmEnvelope(
            key=self._decoded(settings.tutor_kek.get_secret_value()),
            key_id=settings.tutor_kek_id,
        )

    def _decoded(self, encoded: str) -> bytes:
        try:
            return base64.b64decode(encoded, validate=True)
        except binascii.Error as exc:
            msg = "TUTOR_KEK is not base64"
            raise ValueError(msg) from exc


class EmbeddingProvider(Provider):
    """Local embeddings at the width the schema indexes."""

    def provides(self) -> type:
        return EmbeddingPort

    def lifetime(self) -> Lifetime:
        return Lifetime.SINGLETON

    def requires(self) -> tuple[type, ...]:
        return ()

    def create(self, resolved: Mapping[type, object]) -> object:
        return LocalEmbedding(BaseSchema().embedding_dimensions())


class RedactionProvider(Provider):
    """The input-boundary redactor. Stateless, so shared (REQ-MINOR)."""

    def provides(self) -> type:
        return PiiRedactionPort

    def lifetime(self) -> Lifetime:
        return Lifetime.SINGLETON

    def requires(self) -> tuple[type, ...]:
        return ()

    def create(self, resolved: Mapping[type, object]) -> object:
        return RegexPiiRedactor(StandardPiiSteps().steps())


class EngineProvider(Provider):
    """The pool, as the application role. One per process.

    Creating the engine opens nothing; a connection is taken when a
    request first uses its ``RequestConnection``.
    """

    def provides(self) -> type:
        return DatabaseEngine

    def lifetime(self) -> Lifetime:
        return Lifetime.SINGLETON

    def requires(self) -> tuple[type, ...]:
        return (ApplicationSettings,)

    def create(self, resolved: Mapping[type, object]) -> object:
        settings = cast(ApplicationSettings, resolved[ApplicationSettings])
        return DatabaseEngine(ApplicationDatabaseUrl(settings).value())


class KnowledgeBaseProvider(Provider):
    """Reads approved chunks on the request's connection (REQ-KB)."""

    def provides(self) -> type:
        return KnowledgeBasePort

    def lifetime(self) -> Lifetime:
        return Lifetime.REQUEST

    def requires(self) -> tuple[type, ...]:
        return (TransactionConnection, EmbeddingPort, CipherPort)

    def create(self, resolved: Mapping[type, object]) -> object:
        return PgVectorKnowledgeBase(
            cast(TransactionConnection, resolved[TransactionConnection]),
            cast(EmbeddingPort, resolved[EmbeddingPort]),
            cast(CipherPort, resolved[CipherPort]),
            VectorLiteral(),
            CosineConfidence(),
            CitedSources(),
        )


class PolicyProvider(Provider):
    """Reads the policy in force on the request's connection (REQ-POLICY)."""

    def provides(self) -> type:
        return PolicyArtifactPort

    def lifetime(self) -> Lifetime:
        return Lifetime.REQUEST

    def requires(self) -> tuple[type, ...]:
        return (TransactionConnection, ClockPort, CipherPort)

    def create(self, resolved: Mapping[type, object]) -> object:
        return VersionedPolicyCard(
            cast(TransactionConnection, resolved[TransactionConnection]),
            cast(ClockPort, resolved[ClockPort]),
            PolicyCardCodec(cast(CipherPort, resolved[CipherPort])),
        )


class HistoryFieldSetting:
    """Parse ``HISTORY_FIELDS``. Unset is refused. Blank is the empty set."""

    def parse(self, raw: str | None) -> HistoryFieldSet:
        """Return the deployment's field set. ``None`` has no default."""
        if raw is None:
            msg = "HISTORY_FIELDS is not set. Export it."
            raise ValueError(msg)
        names = tuple(part.strip() for part in raw.split(",") if part.strip())
        return HistoryFieldSet.model_validate({"fields": names})


class HistoryFieldSetProvider(Provider):
    """The history minimum, parsed once. The gate and the adapter share it."""

    def provides(self) -> type:
        return HistoryFieldSet

    def lifetime(self) -> Lifetime:
        return Lifetime.SINGLETON

    def requires(self) -> tuple[type, ...]:
        return (ApplicationSettings,)

    def create(self, resolved: Mapping[type, object]) -> object:
        settings = cast(ApplicationSettings, resolved[ApplicationSettings])
        return HistoryFieldSetting().parse(settings.history_fields)


class HistoryProvider(Provider):
    """Allowlisted history on the request's connection (REQ-HISTORY)."""

    def provides(self) -> type:
        return LearnerHistoryPort

    def lifetime(self) -> Lifetime:
        return Lifetime.REQUEST

    def requires(self) -> tuple[type, ...]:
        return (TransactionConnection, CipherPort, ClockPort, HistoryFieldSet)

    def create(self, resolved: Mapping[type, object]) -> object:
        return PostgresLearnerHistory(
            cast(TransactionConnection, resolved[TransactionConnection]),
            cast(CipherPort, resolved[CipherPort]),
            cast(ClockPort, resolved[ClockPort]),
            cast(HistoryFieldSet, resolved[HistoryFieldSet]),
            HistoryOutcomeCodec(),
        )


class PermissionGateProvider(Provider):
    """The gate that runs before retrieval. Request-scoped with the policy."""

    def provides(self) -> type:
        return ContextPermissionGate

    def lifetime(self) -> Lifetime:
        return Lifetime.REQUEST

    def requires(self) -> tuple[type, ...]:
        return (PolicyArtifactPort, HistoryFieldSet, VerdictCitation)

    def create(self, resolved: Mapping[type, object]) -> object:
        return ContextPermissionGate(
            cast(PolicyArtifactPort, resolved[PolicyArtifactPort]),
            cast(HistoryFieldSet, resolved[HistoryFieldSet]),
            PrototypeCopy().permission_rules(),
            cast(VerdictCitation, resolved[VerdictCitation]),
        )


class ConflictGateProvider(Provider):
    """The gate that runs before generation. The threshold is not a default."""

    def provides(self) -> type:
        return ConflictAmbiguityGate

    def lifetime(self) -> Lifetime:
        return Lifetime.REQUEST

    def requires(self) -> tuple[type, ...]:
        return (
            PolicyArtifactPort,
            ApplicationSettings,
            VerdictCitation,
            ConfidenceThreshold,
            SnippetContradiction,
        )

    def create(self, resolved: Mapping[type, object]) -> object:
        settings = cast(ApplicationSettings, resolved[ApplicationSettings])
        threshold = settings.conflict_confidence_threshold
        if threshold is None:
            msg = "CONFLICT_CONFIDENCE_THRESHOLD is not set. Export it."
            raise ValueError(msg)
        return ConflictAmbiguityGate(
            cast(PolicyArtifactPort, resolved[PolicyArtifactPort]),
            threshold,
            PrototypeCopy().conflict_rules(),
            cast(VerdictCitation, resolved[VerdictCitation]),
            cast(ConfidenceThreshold, resolved[ConfidenceThreshold]),
            cast(SnippetContradiction, resolved[SnippetContradiction]),
        )


class SensitivityGateProvider(Provider):
    """The first gate after generation."""

    def provides(self) -> type:
        return SensitivityHighStakesGate

    def lifetime(self) -> Lifetime:
        return Lifetime.REQUEST

    def requires(self) -> tuple[type, ...]:
        return (PolicyArtifactPort, VerdictCitation)

    def create(self, resolved: Mapping[type, object]) -> object:
        copy = PrototypeCopy()
        return SensitivityHighStakesGate(
            cast(PolicyArtifactPort, resolved[PolicyArtifactPort]),
            copy.flagged_categories(),
            copy.sensitivity_rules(),
            cast(VerdictCitation, resolved[VerdictCitation]),
        )


class DriftGateProvider(Provider):
    """The last gate before the tutor sees the turn."""

    def provides(self) -> type:
        return DriftAnomalyGate

    def lifetime(self) -> Lifetime:
        return Lifetime.REQUEST

    def requires(self) -> tuple[type, ...]:
        return (PolicyArtifactPort, VerdictCitation)

    def create(self, resolved: Mapping[type, object]) -> object:
        copy = PrototypeCopy()
        return DriftAnomalyGate(
            cast(PolicyArtifactPort, resolved[PolicyArtifactPort]),
            copy.drift_envelope(),
            copy.session_envelope(),
            copy.drift_rules(),
            cast(VerdictCitation, resolved[VerdictCitation]),
        )


class TemplateProvider(Provider):
    """The fixed template. Stateless, so shared."""

    def provides(self) -> type:
        return PromptTemplatePort

    def lifetime(self) -> Lifetime:
        return Lifetime.SINGLETON

    def requires(self) -> tuple[type, ...]:
        return ()

    def create(self, resolved: Mapping[type, object]) -> object:
        copy = PrototypeCopy()
        return FixedPromptTemplate(
            version=copy.template_version(),
            role=copy.role(),
            structure=copy.structure(),
            tone=copy.tone(),
            disclosure=copy.disclosure(),
        )


class LanguageModelProvider(Provider):
    """The pinned local model. The SHA comes from the runtime pin, not a tag."""

    def provides(self) -> type:
        return LanguageModelPort

    def lifetime(self) -> Lifetime:
        return Lifetime.SINGLETON

    def requires(self) -> tuple[type, ...]:
        return (ApplicationSettings,)

    def create(self, resolved: Mapping[type, object]) -> object:
        settings = cast(ApplicationSettings, resolved[ApplicationSettings])
        if settings.model_pin_path is None:
            msg = "MODEL_PIN_PATH is not set. Point it at config/runtime.toml."
            raise ValueError(msg)
        return OllamaLanguageModel(
            ModelRevision(PinnedRevision(settings.model_pin_path).sha()),
            UrllibOllamaEndpoint(settings.ollama_base_url, ModelfileWeights()),
            PrototypeCopy().decoding(),
            PinnedModelName(),
        )


class GrammarProvider(Provider):
    """Grammar findings. Stateless, so shared."""

    def provides(self) -> type:
        return GrammarCheckPort

    def lifetime(self) -> Lifetime:
        return Lifetime.SINGLETON

    def requires(self) -> tuple[type, ...]:
        return ()

    def create(self, resolved: Mapping[type, object]) -> object:
        return PatternGrammarCheck(MinorGrammarPatterns().patterns())


class SafetyProvider(Provider):
    """Safety flags. Stateless, so shared."""

    def provides(self) -> type:
        return SafetyClassifierPort

    def lifetime(self) -> Lifetime:
        return Lifetime.SINGLETON

    def requires(self) -> tuple[type, ...]:
        return ()

    def create(self, resolved: Mapping[type, object]) -> object:
        return CategorySafetyClassifier(MinorSafetyRules().rules())


class SourceSupportProvider(Provider):
    """Unsupported spans stay on the report. Stateless, so shared."""

    def provides(self) -> type:
        return SourceSupportPort

    def lifetime(self) -> Lifetime:
        return Lifetime.SINGLETON

    def requires(self) -> tuple[type, ...]:
        return ()

    def create(self, resolved: Mapping[type, object]) -> object:
        return SentenceSourceSupport(SentenceSplitter())


class GenerationAgentProvider(Provider):
    """Template, model and the three checks. No retriever (REQ-COMP)."""

    def provides(self) -> type:
        return GenerationAgent

    def lifetime(self) -> Lifetime:
        return Lifetime.SINGLETON

    def requires(self) -> tuple[type, ...]:
        return (
            PromptTemplatePort,
            LanguageModelPort,
            GrammarCheckPort,
            SafetyClassifierPort,
            SourceSupportPort,
        )

    def create(self, resolved: Mapping[type, object]) -> object:
        return ContentGenerationAgent(
            cast(PromptTemplatePort, resolved[PromptTemplatePort]),
            cast(LanguageModelPort, resolved[LanguageModelPort]),
            cast(GrammarCheckPort, resolved[GrammarCheckPort]),
            cast(SafetyClassifierPort, resolved[SafetyClassifierPort]),
            cast(SourceSupportPort, resolved[SourceSupportPort]),
            PrototypeCopy().disclosure(),
        )


class OrchestratorProvider(Provider):
    """The LangGraph turn. Request-scoped: its gates read this request's card."""

    def provides(self) -> type:
        return TurnOrchestrator

    def lifetime(self) -> Lifetime:
        return Lifetime.REQUEST

    def requires(self) -> tuple[type, ...]:
        return (
            ContextPermissionGate,
            RetrievalGuard,
            ConflictAmbiguityGate,
            GenerationGuard,
            SensitivityHighStakesGate,
            DriftAnomalyGate,
        )

    def create(self, resolved: Mapping[type, object]) -> object:
        registry = GateRegistry(
            (
                cast(ContextPermissionGate, resolved[ContextPermissionGate]),
                cast(ConflictAmbiguityGate, resolved[ConflictAmbiguityGate]),
                cast(SensitivityHighStakesGate, resolved[SensitivityHighStakesGate]),
                cast(DriftAnomalyGate, resolved[DriftAnomalyGate]),
            )
        )
        return LangGraphTurnOrchestrator(
            TurnNodes(
                cast(RetrievalGuard, resolved[RetrievalGuard]),
                cast(GenerationGuard, resolved[GenerationGuard]),
                registry.at("sensitivity_and_high_stakes"),
                registry.at("drift_and_anomaly"),
            )
        )


class PrepareTurnProvider(Provider):
    """Redaction and scope cues. Stateless, so shared."""

    def provides(self) -> type:
        return PrepareTurn

    def lifetime(self) -> Lifetime:
        return Lifetime.SINGLETON

    def requires(self) -> tuple[type, ...]:
        return (PiiRedactionPort, SafetyClassifierPort)

    def create(self, resolved: Mapping[type, object]) -> object:
        return PrepareTurn(
            cast(PiiRedactionPort, resolved[PiiRedactionPort]),
            cast(SafetyClassifierPort, resolved[SafetyClassifierPort]),
            PrototypeCopy().unvetted_source_categories(),
        )


class ApplicationContainer:
    """Build the object graph. Nothing is constructed at import.

    ``build`` registers every provider and runs ``LifetimeValidation``, so a
    singleton that captures request-scoped state refuses to boot.

    The request path above is written out provider by provider. The
    dashboard's use cases below repeat one shape — three stage handlers and
    the service that holds them — so they are registered through the base
    providers in ``di/registration.py``. Each still names its concrete
    class and the exact types it requires, here and nowhere else.
    """

    def __init__(self, settings: SettingsProvider) -> None:
        self._settings = settings

    def build(self) -> Container:
        """Return a validated container. An invalid graph never starts."""
        container = Container(self.providers())
        container.validate()
        return container

    def providers(self) -> tuple[Provider, ...]:
        """Every registration, so the lifetime of each is inspectable."""
        return (
            *self._request_path(),
            *self._audit_read(),
            *self._dashboard(),
        )

    def _request_path(self) -> tuple[Provider, ...]:
        return (
            self._settings,
            ConstructorProvider(
                SystemClock, Lifetime.SINGLETON, (), provides=ClockPort
            ),
            CipherProvider(),
            EmbeddingProvider(),
            RedactionProvider(),
            StatelessProvider(AuditRecordHash),
            EngineProvider(),
            ConstructorProvider(
                RequestConnection,
                Lifetime.REQUEST,
                (DatabaseEngine,),
                provides=TransactionConnection,
            ),
            ConstructorProvider(
                SqlAlchemyUnitOfWork,
                Lifetime.REQUEST,
                (TransactionConnection,),
                provides=UnitOfWorkPort,
            ),
            ConstructorProvider(
                PostgresAuditSink,
                Lifetime.REQUEST,
                (TransactionConnection, CipherPort, AuditRecordHash),
                provides=AuditSinkPort,
            ),
            KnowledgeBaseProvider(),
            PolicyProvider(),
            HistoryFieldSetProvider(),
            HistoryProvider(),
            ConstructorProvider(
                PostgresTutoringSession,
                Lifetime.REQUEST,
                (TransactionConnection,),
                provides=TutoringSessionPort,
            ),
            PermissionGateProvider(),
            ConflictGateProvider(),
            SensitivityGateProvider(),
            DriftGateProvider(),
            ConstructorProvider(
                DataRetrievalAgent,
                Lifetime.REQUEST,
                (KnowledgeBasePort, LearnerHistoryPort),
                provides=RetrievalAgent,
            ),
            ConstructorProvider(
                RetrieveIfPermitted,
                Lifetime.REQUEST,
                (ContextPermissionGate, RetrievalAgent),
                provides=RetrievalGuard,
            ),
            TemplateProvider(),
            LanguageModelProvider(),
            GrammarProvider(),
            SafetyProvider(),
            SourceSupportProvider(),
            GenerationAgentProvider(),
            ConstructorProvider(
                GenerateIfConsistent,
                Lifetime.REQUEST,
                (ConflictAmbiguityGate, GenerationAgent),
                provides=GenerationGuard,
            ),
            OrchestratorProvider(),
            StatelessProvider(GateRows),
            StatelessProvider(PolicyRuleLookup),
            ConstructorProvider(
                VerdictCitation, Lifetime.SINGLETON, (PolicyRuleLookup,)
            ),
            ConstructorProvider(
                ConfidenceThreshold, Lifetime.SINGLETON, (PolicyRuleLookup,)
            ),
            StatelessProvider(SnippetContradiction),
            StatelessProvider(CitedContextDigest),
            ConstructorProvider(
                TurnRecordBuilder,
                Lifetime.SINGLETON,
                (AuditRecordHash, GateRows, CitedContextDigest),
            ),
            PrepareTurnProvider(),
            StatelessProvider(SessionBaselineCalculator),
            ConstructorProvider(
                ExecuteTurn,
                Lifetime.REQUEST,
                (
                    UnitOfWorkPort,
                    TurnOrchestrator,
                    AuditSinkPort,
                    PolicyArtifactPort,
                    TurnRecordBuilder,
                    ClockPort,
                    TutoringSessionPort,
                    AuditQueryPort,
                    SessionBaselineCalculator,
                ),
            ),
            StatelessProvider(FinaliseTurn),
            ConstructorProvider(
                ConductTurn, Lifetime.REQUEST, (PrepareTurn, ExecuteTurn, FinaliseTurn)
            ),
        )

    def _audit_read(self) -> tuple[Provider, ...]:
        """The adapters and stateless helpers the dashboard reads through."""
        singleton = Lifetime.SINGLETON
        request = Lifetime.REQUEST
        connection = TransactionConnection
        return (
            ConstructorProvider(SealedValue, singleton, (CipherPort,)),
            ConstructorProvider(AuditRecordDecoder, singleton, (SealedValue,)),
            StatelessProvider(ActionRecordHash),
            ConstructorProvider(
                ChainVerifier, singleton, (AuditRecordHash, ActionRecordHash)
            ),
            StatelessProvider(ActionRules),
            StatelessProvider(SessionEvents),
            StatelessProvider(SseEncoder),
            StatelessProvider(DraftComparison),
            ConstructorProvider(
                PostgresAuditQuery,
                request,
                (connection, AuditRecordDecoder),
                provides=AuditQueryPort,
            ),
            ConstructorProvider(
                PostgresHumanAction,
                request,
                (connection, SealedValue, ActionRecordHash),
                provides=HumanActionPort,
            ),
            ConstructorProvider(
                PostgresSessionDirectory,
                request,
                (connection, SealedValue, ClockPort),
                provides=SessionDirectoryPort,
            ),
            ConstructorProvider(
                PostgresCohortReport,
                request,
                (connection,),
                provides=CohortReportPort,
            ),
        )

    def _dashboard(self) -> tuple[Provider, ...]:
        """Each dashboard use case: prepare, execute, finalise, service."""
        request = Lifetime.REQUEST
        unit = UnitOfWorkPort
        audit = AuditQueryPort
        directory = SessionDirectoryPort
        return (
            # Record a tutor action (REQ-DASH).
            ConstructorProvider(
                PrepareAction,
                Lifetime.SINGLETON,
                (PiiRedactionPort, SafetyClassifierPort),
            ),
            ConstructorProvider(
                ExecuteAction,
                request,
                (
                    unit,
                    audit,
                    directory,
                    HumanActionPort,
                    ClockPort,
                    ActionRecordHash,
                    ActionRules,
                ),
            ),
            StatelessProvider(FinaliseAction),
            ServiceProvider(
                RecordHumanAction, PrepareAction, ExecuteAction, FinaliseAction
            ),
            # One session's audit chain.
            StatelessProvider(PrepareAudit),
            ConstructorProvider(
                ExecuteAudit, request, (unit, audit, directory, ChainVerifier)
            ),
            StatelessProvider(FinaliseAudit),
            ServiceProvider(ReadAudit, PrepareAudit, ExecuteAudit, FinaliseAudit),
            # One turn's audit page.
            StatelessProvider(PrepareTurnRead),
            ConstructorProvider(
                ExecuteTurnRead, request, (unit, audit, directory, AuditRecordHash)
            ),
            StatelessProvider(FinaliseTurnRead),
            ServiceProvider(
                ReadTurn, PrepareTurnRead, ExecuteTurnRead, FinaliseTurnRead
            ),
            # Session list, one session, opening, learners.
            StatelessProvider(PrepareSessionList),
            ConstructorProvider(ExecuteSessionList, request, (unit, directory)),
            StatelessProvider(FinaliseSessionList),
            ServiceProvider(
                ListSessions,
                PrepareSessionList,
                ExecuteSessionList,
                FinaliseSessionList,
            ),
            StatelessProvider(PrepareSession),
            ConstructorProvider(ExecuteSession, request, (unit, directory)),
            StatelessProvider(FinaliseSession),
            ServiceProvider(
                ReadSession, PrepareSession, ExecuteSession, FinaliseSession
            ),
            StatelessProvider(PrepareOpenSession),
            ConstructorProvider(
                ExecuteOpenSession, request, (unit, directory, ClockPort)
            ),
            ServiceProvider(
                OpenSession, PrepareOpenSession, ExecuteOpenSession, FinaliseSession
            ),
            StatelessProvider(PrepareLearnerList),
            ConstructorProvider(ExecuteLearnerList, request, (unit, directory)),
            StatelessProvider(FinaliseLearnerList),
            ServiceProvider(
                ListLearners,
                PrepareLearnerList,
                ExecuteLearnerList,
                FinaliseLearnerList,
            ),
            # The session event stream.
            StatelessProvider(PrepareStream),
            ConstructorProvider(
                ExecuteStream,
                request,
                (unit, audit, directory, SessionEvents, SseEncoder),
            ),
            StatelessProvider(FinaliseStream),
            ServiceProvider(
                StreamSession, PrepareStream, ExecuteStream, FinaliseStream
            ),
            # Replay a recorded turn (rule 7).
            StatelessProvider(PrepareReplay),
            ConstructorProvider(
                ExecuteReplay,
                request,
                (
                    unit,
                    audit,
                    GenerationAgent,
                    AuditRecordHash,
                    DraftComparison,
                    CitedContextDigest,
                ),
            ),
            StatelessProvider(FinaliseReplay),
            ServiceProvider(ReplayTurn, PrepareReplay, ExecuteReplay, FinaliseReplay),
            # Cohort counts for the periodic review.
            StatelessProvider(PrepareCohort),
            ConstructorProvider(ExecuteCohort, request, (unit, CohortReportPort)),
            StatelessProvider(FinaliseCohort),
            ServiceProvider(ReportCohort, PrepareCohort, ExecuteCohort, FinaliseCohort),
        )
