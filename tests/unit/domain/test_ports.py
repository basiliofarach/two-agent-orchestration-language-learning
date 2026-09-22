"""ABC mechanics and the method sets DEC-0001 requires."""

from abc import ABC

import pytest

from tutor_core.domain.ports import (
    AuditSinkPort,
    CipherPort,
    ClockPort,
    EmbeddingPort,
    GrammarCheckPort,
    KnowledgeBasePort,
    LanguageModelPort,
    LearnerHistoryPort,
    OversightGatePort,
    PiiRedactionPort,
    PolicyArtifactPort,
    PromptTemplatePort,
    SafetyClassifierPort,
    SourceSupportPort,
    TransactionalWork,
    UnitOfWorkPort,
)


class _ImplementedMethod:
    def run(self, *args: object, **kwargs: object) -> None:
        return None


class PortCatalogue:
    """The ports, plus partial and complete in-test stubs."""

    def types(self) -> tuple[type[ABC], ...]:
        return (
            PiiRedactionPort,
            KnowledgeBasePort,
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
