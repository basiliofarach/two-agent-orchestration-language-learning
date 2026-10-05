"""ABC mechanics and the method sets DEC-0001 requires."""

import inspect
from abc import ABC
from typing import get_type_hints

import pytest

from tutor_core.domain.models.retrieval import RedactedRetrievalRequest
from tutor_core.domain.ports import (
    AuditSinkPort,
    CipherPort,
    ClockPort,
    CorpusIngestionPort,
    EmbeddingPort,
    GrammarCheckPort,
    KnowledgeBasePort,
    LanguageModelPort,
    LearnerHistoryPort,
    OversightGatePort,
    PiiRedactionPort,
    PolicyArtifactPort,
    PolicyPublicationPort,
    PromptTemplatePort,
    SafetyClassifierPort,
    SourceSupportPort,
    TransactionalWork,
    UnitOfWorkPort,
)
from tutor_core.domain.ports.unit_of_work import TransactionConnection


class _ImplementedMethod:
    def run(self, *args: object, **kwargs: object) -> None:
        return None


class PortCatalogue:
    """The ports, plus partial and complete in-test stubs."""

    def types(self) -> tuple[type[ABC], ...]:
        return (
            PiiRedactionPort,
            KnowledgeBasePort,
            CorpusIngestionPort,
            LearnerHistoryPort,
            EmbeddingPort,
            LanguageModelPort,
            PromptTemplatePort,
            GrammarCheckPort,
            SafetyClassifierPort,
            SourceSupportPort,
            OversightGatePort,
            AuditSinkPort,
            PolicyArtifactPort,
            PolicyPublicationPort,
            ClockPort,
            CipherPort,
            UnitOfWorkPort,
            TransactionalWork,
        )

    def partial(self, port: type[ABC]) -> type[ABC]:
        kept = sorted(port.__abstractmethods__)[1:]
        return self._subclass(port, kept, "Partial")

    def stub(self, port: type[ABC]) -> type[ABC]:
        return self._subclass(port, sorted(port.__abstractmethods__), "Stub")

    def _subclass(
        self,
        port: type[ABC],
        names: list[str],
        prefix: str,
    ) -> type[ABC]:
        namespace = {name: _ImplementedMethod.run for name in names}
        created: type[ABC] = type(f"{prefix}{port.__name__}", (port,), namespace)
        return created


class TestPortInstantiation:
    def test_direct_instantiation_raises_type_error(self) -> None:
        for port in PortCatalogue().types():
            with pytest.raises(TypeError, match="abstract"):
                port()

    def test_partial_implementation_raises_type_error(self) -> None:
        catalogue = PortCatalogue()
        for port in catalogue.types():
            with pytest.raises(TypeError, match="abstract"):
                catalogue.partial(port)()

    def test_full_stub_instantiates(self) -> None:
        catalogue = PortCatalogue()
        for port in catalogue.types():
            instance = catalogue.stub(port)()
            assert isinstance(instance, port)


class TestPortMethodSurface:
    def test_audit_sink_declares_append_only(self) -> None:
        assert AuditSinkPort.__abstractmethods__ == frozenset({"append"})

    def test_language_model_exposes_complete_and_revision_only(self) -> None:
        assert LanguageModelPort.__abstractmethods__ == frozenset(
            {"complete", "revision"}
        )

    def test_knowledge_base_has_no_open_web_method(self) -> None:
        assert KnowledgeBasePort.__abstractmethods__ == frozenset({"retrieve"})

    def test_transaction_connection_reads_but_cannot_connect(self) -> None:
        assert TransactionConnection.__abstractmethods__ == frozenset(
            {"commit", "rollback", "close", "execute", "fetch_one", "fetch_all"}
        )

    def test_persistence_ports_run_on_the_enlisted_connection(self) -> None:
        for method in (
            KnowledgeBasePort.retrieve,
            CorpusIngestionPort.ingest,
            PolicyArtifactPort.current,
            PolicyArtifactPort.version,
            PolicyPublicationPort.publish,
        ):
            assert inspect.iscoroutinefunction(method), method.__qualname__

    def test_knowledge_base_takes_redacted_text_only(self) -> None:
        hints = get_type_hints(KnowledgeBasePort.retrieve)
        assert hints["request"] is RedactedRetrievalRequest

    def test_learner_history_is_read_only(self) -> None:
        assert LearnerHistoryPort.__abstractmethods__ == frozenset({"read"})
        doc = LearnerHistoryPort.__doc__ or ""
        assert "allowlist" in doc
        assert "constructor argument" in doc

    def test_oversight_gate_is_name_and_evaluate(self) -> None:
        assert OversightGatePort.__abstractmethods__ == frozenset({"name", "evaluate"})

    def test_policy_artifact_is_read_only(self) -> None:
        assert PolicyArtifactPort.__abstractmethods__ == frozenset(
            {"current", "version"}
        )

    def test_policy_publication_does_not_select_the_current_version(self) -> None:
        assert PolicyPublicationPort.__abstractmethods__ == frozenset({"publish"})

    def test_corpus_ingestion_does_not_retrieve(self) -> None:
        assert CorpusIngestionPort.__abstractmethods__ == frozenset({"ingest"})

    def test_cipher_is_encrypt_and_decrypt_only(self) -> None:
        assert CipherPort.__abstractmethods__ == frozenset({"encrypt", "decrypt"})

    def test_cipher_holds_no_store_or_key_accessor(self) -> None:
        names = [name for name in dir(CipherPort) if not name.startswith("_")]
        assert sorted(names) == ["decrypt", "encrypt"]

    def test_each_docstring_names_its_requirement_and_boundary(self) -> None:
        for port in PortCatalogue().types():
            doc = port.__doc__ or ""
            assert "Scope boundary" in doc
            assert "REQ-" in doc or "carries no REQ-" in doc
