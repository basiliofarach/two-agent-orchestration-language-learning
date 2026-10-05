"""Registration — the only site that names concrete classes (rule 3).

Providers live here rather than as decorators on implementations. A class that
reaches for its own container is not injected, it is coupled, and the
capability-scoping argument in DEC-0001 rests on a collaborator holding only
what it was handed.

The request path is registered: redaction, retrieval, the policy in force, the
audit sink, and the one connection they share (DEC-0014). Curation is not.
``CorpusIngestionPort`` and ``PolicyPublicationPort`` have no provider, so no
request can ingest a document or publish a policy version (DEC-0001).
"""

import base64
import binascii
from collections.abc import Mapping
from typing import cast

from tutor_api.adapters.checks.pii_redaction import RegexPiiRedactor, StandardPiiSteps
from tutor_api.adapters.llm.local_embedding import LocalEmbedding
from tutor_api.adapters.persistence.aes_gcm_envelope import AesGcmEnvelope
from tutor_api.adapters.persistence.audit_sink import PostgresAuditSink
from tutor_api.adapters.persistence.database import DatabaseEngine, RequestConnection
from tutor_api.adapters.persistence.database_url import ApplicationDatabaseUrl
from tutor_api.adapters.persistence.knowledge_base import (
    CitedSources,
    CosineConfidence,
    PgVectorKnowledgeBase,
    VectorLiteral,
)
from tutor_api.adapters.persistence.schema import BaseSchema
from tutor_api.adapters.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tutor_api.adapters.persistence.versioned_policy import (
    PolicyCardCodec,
    VersionedPolicyCard,
)
from tutor_api.adapters.system_clock import SystemClock
from tutor_api.di.container import Container
from tutor_api.di.lifetime import Lifetime
from tutor_api.di.provider import Provider
from tutor_api.settings import ApplicationSettings
from tutor_core.domain.audit.record_hash import AuditRecordHash
from tutor_core.domain.ports.audit_sink import AuditSinkPort
from tutor_core.domain.ports.cipher import CipherPort
from tutor_core.domain.ports.clock import ClockPort
from tutor_core.domain.ports.embedding import EmbeddingPort
from tutor_core.domain.ports.knowledge_base import KnowledgeBasePort
from tutor_core.domain.ports.pii_redaction import PiiRedactionPort
from tutor_core.domain.ports.policy_artifact import PolicyArtifactPort
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


class ClockProvider(Provider):
    """The wall clock. Replay substitutes a fixed one (rule 7)."""

    def provides(self) -> type:
        return ClockPort

    def lifetime(self) -> Lifetime:
        return Lifetime.SINGLETON

    def requires(self) -> tuple[type, ...]:
        return ()

    def create(self, resolved: Mapping[type, object]) -> object:
        return SystemClock()


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


class RecordHashProvider(Provider):
    """The audit digest. Stateless, so shared."""

    def provides(self) -> type:
        return AuditRecordHash

    def lifetime(self) -> Lifetime:
        return Lifetime.SINGLETON

    def requires(self) -> tuple[type, ...]:
        return ()

    def create(self, resolved: Mapping[type, object]) -> object:
        return AuditRecordHash()


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


class ConnectionProvider(Provider):
    """The request's one connection. Request-scoped: never shared by learners."""

    def provides(self) -> type:
        return TransactionConnection

    def lifetime(self) -> Lifetime:
        return Lifetime.REQUEST

    def requires(self) -> tuple[type, ...]:
        return (DatabaseEngine,)

    def create(self, resolved: Mapping[type, object]) -> object:
        return RequestConnection(cast(DatabaseEngine, resolved[DatabaseEngine]))


class UnitOfWorkProvider(Provider):
    """Commits or rolls back the request's connection."""

    def provides(self) -> type:
        return UnitOfWorkPort

    def lifetime(self) -> Lifetime:
        return Lifetime.REQUEST

    def requires(self) -> tuple[type, ...]:
        return (TransactionConnection,)

    def create(self, resolved: Mapping[type, object]) -> object:
        return SqlAlchemyUnitOfWork(
            cast(TransactionConnection, resolved[TransactionConnection])
        )


class AuditSinkProvider(Provider):
    """Appends on the request's connection, inside its unit of work."""

    def provides(self) -> type:
        return AuditSinkPort

    def lifetime(self) -> Lifetime:
        return Lifetime.REQUEST

    def requires(self) -> tuple[type, ...]:
        return (TransactionConnection, CipherPort, AuditRecordHash)

    def create(self, resolved: Mapping[type, object]) -> object:
        return PostgresAuditSink(
            cast(TransactionConnection, resolved[TransactionConnection]),
            cast(CipherPort, resolved[CipherPort]),
            cast(AuditRecordHash, resolved[AuditRecordHash]),
        )


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


class ApplicationContainer:
    """Build the object graph. Nothing is constructed at import.

    ``settings`` is the one seam: a test hands in fixed configuration, and
    every other registration is the one production uses.
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
            self._settings,
            ClockProvider(),
            CipherProvider(),
            EmbeddingProvider(),
            RedactionProvider(),
            RecordHashProvider(),
            EngineProvider(),
            ConnectionProvider(),
            UnitOfWorkProvider(),
            AuditSinkProvider(),
            KnowledgeBaseProvider(),
            PolicyProvider(),
        )
