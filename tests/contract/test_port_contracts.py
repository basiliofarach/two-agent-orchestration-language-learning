"""Abstract port contracts. Adapter tests subclass these and pass."""

import hashlib
import secrets
from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import UUID

import pytest
from tests.support.samples import Samples

from tutor_core.domain.models.audit import TurnAuditRecord
from tutor_core.domain.models.learner import LearnerHistorySnapshot, LearnerId
from tutor_core.domain.models.retrieval import (
    RetrievalQuery,
    RetrievalResult,
    SourceRef,
)
from tutor_core.domain.models.safety import (
    GrammarFinding,
    ModelCompletion,
    RedactedText,
    RenderedPrompt,
    SafetyFlag,
    SourceSupportReport,
)
from tutor_core.domain.models.turn import TurnState
from tutor_core.domain.models.verdict import GateVerdict
from tutor_core.domain.policy.policy_card import PolicyCard
from tutor_core.domain.ports.audit_sink import AuditSinkPort
from tutor_core.domain.ports.cipher import CipherPort
from tutor_core.domain.ports.clock import ClockPort
from tutor_core.domain.ports.embedding import EmbeddingPort
from tutor_core.domain.ports.grammar_check import GrammarCheckPort
from tutor_core.domain.ports.knowledge_base import KnowledgeBasePort
from tutor_core.domain.ports.language_model import LanguageModelPort
from tutor_core.domain.ports.learner_history import LearnerHistoryPort
from tutor_core.domain.ports.oversight_gate import OversightGatePort
from tutor_core.domain.ports.pii_redaction import PiiRedactionPort
from tutor_core.domain.ports.policy_artifact import PolicyArtifactPort
from tutor_core.domain.ports.prompt_template import PromptTemplatePort
from tutor_core.domain.ports.safety_classifier import SafetyClassifierPort
from tutor_core.domain.ports.source_support import SourceSupportPort
from tutor_core.domain.ports.unit_of_work import (
    TransactionalWork,
    TransactionConnection,
    UnitOfWorkPort,
)


class PiiRedactionPortContract:
    """Every ``PiiRedactionPort`` returns ``RedactedText``."""

    def port(self) -> PiiRedactionPort:
        msg = "subclass must supply a PiiRedactionPort"
        raise NotImplementedError(msg)

    def test_redact_returns_redacted_text(self) -> None:
        redacted = self.port().redact("ada@example.com")
        assert isinstance(redacted, RedactedText)


class KnowledgeBasePortContract:
    """Every ``KnowledgeBasePort`` returns a ``RetrievalResult``."""

    def port(self) -> KnowledgeBasePort:
        msg = "subclass must supply a KnowledgeBasePort"
        raise NotImplementedError(msg)

    def test_retrieve_returns_a_result(self) -> None:
        result = self.port().retrieve(Samples().query())
        assert isinstance(result, RetrievalResult)


class LearnerHistoryPortContract:
    """Every ``LearnerHistoryPort`` reads one learner and does not write."""

    def port(self) -> LearnerHistoryPort:
        msg = "subclass must supply a LearnerHistoryPort"
        raise NotImplementedError(msg)

    def learner_id(self) -> LearnerId:
        return Samples().learner_id()

    def test_read_returns_that_learners_snapshot(self) -> None:
        snapshot = self.port().read(self.learner_id())
        assert isinstance(snapshot, LearnerHistorySnapshot)
        assert snapshot.learner_id == self.learner_id()


class EmbeddingPortContract:
    """Every ``EmbeddingPort`` returns a float vector."""

    def port(self) -> EmbeddingPort:
        msg = "subclass must supply an EmbeddingPort"
        raise NotImplementedError(msg)

    def test_embed_returns_a_float_vector(self) -> None:
        vector = self.port().embed("hello")
        assert isinstance(vector, tuple)
        assert vector
        assert all(isinstance(item, float) for item in vector)


class LanguageModelPortContract:
    """Every ``LanguageModelPort`` completes and reports one revision."""

    def port(self) -> LanguageModelPort:
        msg = "subclass must supply a LanguageModelPort"
        raise NotImplementedError(msg)

    def test_complete_and_revision_agree(self) -> None:
        completion = self.port().complete(Samples().rendered_prompt())
        assert isinstance(completion, ModelCompletion)
        assert self.port().revision() == completion.model_revision


class PromptTemplatePortContract:
    """Every ``PromptTemplatePort`` renders a versioned prompt."""

    def port(self) -> PromptTemplatePort:
        msg = "subclass must supply a PromptTemplatePort"
        raise NotImplementedError(msg)

    def test_render_returns_the_template_version(self) -> None:
        rendered = self.port().render(
            "explain greetings",
            Samples().retrieval(),
            Samples().history(),
        )
        assert isinstance(rendered, RenderedPrompt)
        assert rendered.template_version == self.port().template_version()


class GrammarCheckPortContract:
    """Every ``GrammarCheckPort`` returns grammar findings."""

    def port(self) -> GrammarCheckPort:
        msg = "subclass must supply a GrammarCheckPort"
        raise NotImplementedError(msg)

    def test_check_returns_findings(self) -> None:
        findings = self.port().check("he go")
        assert isinstance(findings, tuple)
        assert all(isinstance(item, GrammarFinding) for item in findings)


class SafetyClassifierPortContract:
    """Every ``SafetyClassifierPort`` returns safety flags."""

    def port(self) -> SafetyClassifierPort:
        msg = "subclass must supply a SafetyClassifierPort"
        raise NotImplementedError(msg)

    def test_classify_returns_flags(self) -> None:
        flags = self.port().classify("hello")
        assert isinstance(flags, tuple)
        assert all(isinstance(item, SafetyFlag) for item in flags)


class SourceSupportPortContract:
    """Every ``SourceSupportPort`` returns both span lists."""

    def port(self) -> SourceSupportPort:
        msg = "subclass must supply a SourceSupportPort"
        raise NotImplementedError(msg)

    def test_verify_returns_supported_and_unsupported(self) -> None:
        report = self.port().verify("Hola means hello.", (Samples().source(),))
        assert isinstance(report, SourceSupportReport)
        assert isinstance(report.supported, tuple)
        assert isinstance(report.unsupported, tuple)


class OversightGatePortContract:
    """Every gate returns a verdict and leaves the turn unchanged."""

    def port(self) -> OversightGatePort:
        msg = "subclass must supply an OversightGatePort"
        raise NotImplementedError(msg)

    def test_evaluate_returns_a_verdict_without_mutating_the_turn(self) -> None:
        turn = Samples().turn()
        before = turn.model_dump()
        verdict = self.port().evaluate(turn)
        assert isinstance(verdict, GateVerdict)
        assert verdict.decision in {"pass", "pause", "stop"}
        assert turn.model_dump() == before


class AuditSinkPortContract:
    """Every ``AuditSinkPort`` accepts one record through ``append``."""

    def port(self) -> AuditSinkPort:
        msg = "subclass must supply an AuditSinkPort"
        raise NotImplementedError(msg)

    async def test_append_accepts_a_record(self) -> None:
        record = Samples().audit_record()
        assert isinstance(record, TurnAuditRecord)
        assert await self.port().append(record) is None


class PolicyArtifactPortContract:
    """Every ``PolicyArtifactPort`` version matches the current card."""

    def port(self) -> PolicyArtifactPort:
        msg = "subclass must supply a PolicyArtifactPort"
        raise NotImplementedError(msg)

    def test_version_matches_the_current_card(self) -> None:
        card = self.port().current()
        assert isinstance(card, PolicyCard)
        assert self.port().version() == card.version


class ClockPortContract:
    """Every ``ClockPort`` returns a timezone-aware instant."""

    def port(self) -> ClockPort:
        msg = "subclass must supply a ClockPort"
        raise NotImplementedError(msg)

    def test_now_is_timezone_aware(self) -> None:
        instant = self.port().now()
        assert isinstance(instant, datetime)
        assert instant.tzinfo is not None


class CipherPortContract:
    """Every ``CipherPort`` round-trips, hides the plaintext, and authenticates."""

    def port(self) -> CipherPort:
        msg = "subclass must supply a CipherPort"
        raise NotImplementedError(msg)

    def test_encrypt_then_decrypt_returns_the_plaintext(self) -> None:
        port = self.port()
        assert port.decrypt(port.encrypt(b"hola, como estas")) == b"hola, como estas"

    def test_envelope_carries_the_dec0012_header(self) -> None:
        envelope = self.port().encrypt(b"hola")
        assert envelope[0] == 1
        assert len(envelope) >= 45

    def test_equal_plaintexts_produce_different_envelopes(self) -> None:
        port = self.port()
        assert port.encrypt(b"A1") != port.encrypt(b"A1")

    def test_envelope_does_not_contain_the_plaintext(self) -> None:
        assert b"proficiency" not in self.port().encrypt(b"proficiency")

    def test_a_tampered_envelope_raises(self) -> None:
        port = self.port()
        envelope = bytearray(port.encrypt(b"hola"))
        envelope[-1] ^= 0xFF
        with pytest.raises(ValueError, match="authentication"):
            port.decrypt(bytes(envelope))


class _Redactor(PiiRedactionPort):
    def redact(self, text: str) -> RedactedText:
        return RedactedText(text=text, redacted_categories=(), redaction_count=0)


class _Knowledge(KnowledgeBasePort):
    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        return Samples().retrieval()


class _History(LearnerHistoryPort):
    def __init__(self, field_allowlist: tuple[str, ...]) -> None:
        self._field_allowlist = field_allowlist

    def read(self, learner_id: LearnerId) -> LearnerHistorySnapshot:
        return LearnerHistorySnapshot(
            learner_id=learner_id,
            proficiency_level="A1",
            events=(),
        )


class _Embedding(EmbeddingPort):
    def embed(self, text: str) -> tuple[float, ...]:
        return (1.0, 0.0)


class _Model(LanguageModelPort):
    def complete(self, prompt: RenderedPrompt) -> ModelCompletion:
        return Samples().completion()

    def revision(self) -> str:
        return Samples().completion().model_revision


class _Template(PromptTemplatePort):
    def render(
        self,
        task: str,
        context: RetrievalResult,
        history: LearnerHistorySnapshot,
    ) -> RenderedPrompt:
        return RenderedPrompt(text=task, template_version=self.template_version())

    def template_version(self) -> str:
        return "tpl-1"


class _Grammar(GrammarCheckPort):
    def check(self, text: str) -> tuple[GrammarFinding, ...]:
        return ()


class _Safety(SafetyClassifierPort):
    def classify(self, text: str) -> tuple[SafetyFlag, ...]:
        return ()


class _Support(SourceSupportPort):
    def verify(
        self,
        draft: str,
        sources: tuple[SourceRef, ...],
    ) -> SourceSupportReport:
        return Samples().support()


class _Gate(OversightGatePort):
    def name(self) -> str:
        return "context_and_permission"

    def evaluate(self, turn: TurnState) -> GateVerdict:
        return Samples().verdict()


class _Audit(AuditSinkPort):
    def __init__(self) -> None:
        self.records: list[TurnAuditRecord] = []

    async def append(self, record: TurnAuditRecord) -> None:
        self.records.append(record)


class _Policy(PolicyArtifactPort):
    def current(self) -> PolicyCard:
        return Samples().policy_card()

    def version(self) -> str:
        return Samples().policy_card().version


class _Cipher(CipherPort):
    """Shape-correct stub, not production cryptography (DEC-0012 envelope)."""

    _VERSION = 1
    _KEY_ID = UUID("00000000-0000-4000-8000-000000000001").bytes
    _HEADER = 29
    _TAG = 16

    def encrypt(self, plaintext: bytes) -> bytes:
        nonce = secrets.token_bytes(12)
        header = bytes([self._VERSION]) + self._KEY_ID + nonce
        body = self._xor(plaintext, nonce)
        return header + body + self._tag(header + body)

    def decrypt(self, envelope: bytes) -> bytes:
        header = envelope[: self._HEADER]
        body = envelope[self._HEADER : -self._TAG]
        if self._tag(header + body) != envelope[-self._TAG :]:
            msg = "envelope failed authentication"
            raise ValueError(msg)
        return self._xor(body, header[17:29])

    def _tag(self, data: bytes) -> bytes:
        return hashlib.sha256(data).digest()[: self._TAG]

    def _xor(self, data: bytes, nonce: bytes) -> bytes:
        return bytes(
            a ^ b for a, b in zip(data, self._stream(nonce, len(data)), strict=True)
        )

    def _stream(self, nonce: bytes, length: int) -> bytes:
        out = bytearray()
        block = 0
        while len(out) < length:
            out += hashlib.sha256(nonce + block.to_bytes(4, "big")).digest()
            block += 1
        return bytes(out[:length])


class _Clock(ClockPort):
    def now(self) -> datetime:
        return datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


class TestStubPiiRedactionPort(PiiRedactionPortContract):
    def port(self) -> PiiRedactionPort:
        return _Redactor()


class TestStubKnowledgeBasePort(KnowledgeBasePortContract):
    def port(self) -> KnowledgeBasePort:
        return _Knowledge()


class TestStubLearnerHistoryPort(LearnerHistoryPortContract):
    def port(self) -> LearnerHistoryPort:
        return _History(field_allowlist=("proficiency_level", "events"))


class TestStubEmbeddingPort(EmbeddingPortContract):
    def port(self) -> EmbeddingPort:
        return _Embedding()


class TestStubLanguageModelPort(LanguageModelPortContract):
    def port(self) -> LanguageModelPort:
        return _Model()


class TestStubPromptTemplatePort(PromptTemplatePortContract):
    def port(self) -> PromptTemplatePort:
        return _Template()


class TestStubGrammarCheckPort(GrammarCheckPortContract):
    def port(self) -> GrammarCheckPort:
        return _Grammar()


class TestStubSafetyClassifierPort(SafetyClassifierPortContract):
    def port(self) -> SafetyClassifierPort:
        return _Safety()


class TestStubSourceSupportPort(SourceSupportPortContract):
    def port(self) -> SourceSupportPort:
        return _Support()


class TestStubOversightGatePort(OversightGatePortContract):
    def port(self) -> OversightGatePort:
        return _Gate()


class TestStubAuditSinkPort(AuditSinkPortContract):
    def port(self) -> AuditSinkPort:
        return _Audit()


class TestStubPolicyArtifactPort(PolicyArtifactPortContract):
    def port(self) -> PolicyArtifactPort:
        return _Policy()


class _CompletedWork(TransactionalWork):
    def __init__(self) -> None:
        self.ran = False

    async def run(self, connection: TransactionConnection) -> None:
        self.ran = True


class _MemoryConnection(TransactionConnection):
    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def execute(
        self,
        statement: str,
        parameters: Mapping[str, object] | None = None,
    ) -> None:
        return None

    async def fetch_one(
        self,
        statement: str,
        parameters: Mapping[str, object],
    ) -> tuple[object, ...] | None:
        return None


class _MemoryUnitOfWork(UnitOfWorkPort):
    async def run(self, work: TransactionalWork) -> None:
        await work.run(_MemoryConnection())


class UnitOfWorkPortContract:
    """Every ``UnitOfWorkPort`` runs the enlisted work."""

    def port(self) -> UnitOfWorkPort:
        msg = "subclass must supply a UnitOfWorkPort"
        raise NotImplementedError(msg)

    async def test_run_executes_the_enlisted_work(self) -> None:
        work = _CompletedWork()
        await self.port().run(work)
        assert work.ran


class TestStubCipherPort(CipherPortContract):
    def port(self) -> CipherPort:
        return _Cipher()


class TestStubClockPort(ClockPortContract):
    def port(self) -> ClockPort:
        return _Clock()


class TestStubUnitOfWorkPort(UnitOfWorkPortContract):
    def port(self) -> UnitOfWorkPort:
        return _MemoryUnitOfWork()
