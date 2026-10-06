"""Stubs for the turn's collaborators, shared by unit and integration tests."""

import hashlib

from tests.support.samples import Samples
from tests.support.scripted_model import ScriptedLanguageModel
from tutor_core.application.agents.generation import ContentGenerationAgent
from tutor_core.domain.models.learner import (
    HistoryFieldSet,
    LearnerHistorySnapshot,
    LearnerId,
)
from tutor_core.domain.models.retrieval import (
    RedactedRetrievalRequest,
    RetrievalResult,
    Snippet,
)
from tutor_core.domain.models.safety import (
    GrammarFinding,
    ModelCompletion,
    RenderedPrompt,
    SafetyFlag,
    SourceSupportReport,
)
from tutor_core.domain.models.turn import TurnState
from tutor_core.domain.models.verdict import GateDecision, GateVerdict
from tutor_core.domain.ports.grammar_check import GrammarCheckPort
from tutor_core.domain.ports.knowledge_base import KnowledgeBasePort
from tutor_core.domain.ports.learner_history import LearnerHistoryPort
from tutor_core.domain.ports.oversight_gate import OversightGatePort
from tutor_core.domain.ports.prompt_template import PromptTemplatePort
from tutor_core.domain.ports.safety_classifier import SafetyClassifierPort
from tutor_core.domain.ports.source_support import SourceSupportPort


class CountingKnowledge(KnowledgeBasePort):
    def __init__(self) -> None:
        self.calls = 0

    async def retrieve(self, request: RedactedRetrievalRequest) -> RetrievalResult:
        self.calls += 1
        return Samples().retrieval()


class EmptyKnowledge(KnowledgeBasePort):
    async def retrieve(self, request: RedactedRetrievalRequest) -> RetrievalResult:
        return RetrievalResult(snippets=(), sources=(), confidence=0.0)


class CountingHistory(LearnerHistoryPort):
    def __init__(self) -> None:
        self.calls = 0
        self.requested: list[HistoryFieldSet] = []

    async def read(
        self, learner_id: LearnerId, requested: HistoryFieldSet
    ) -> LearnerHistorySnapshot:
        self.calls += 1
        self.requested.append(requested)
        return Samples().history()


class FixedTemplate(PromptTemplatePort):
    def render(
        self,
        task: str,
        context: RetrievalResult,
        history: LearnerHistorySnapshot,
    ) -> RenderedPrompt:
        return RenderedPrompt(text=task, template_version=self.template_version())

    def template_version(self) -> str:
        return "tpl-1"


class FindingGrammar(GrammarCheckPort):
    def check(self, text: str) -> tuple[GrammarFinding, ...]:
        return (Samples().grammar(),)


class FlaggingSafety(SafetyClassifierPort):
    """Flags text containing ``web`` with the flags it was given."""

    def __init__(self, flags: tuple[SafetyFlag, ...] = ()) -> None:
        self._flags = flags
        self.texts: list[str] = []

    def classify(self, text: str) -> tuple[SafetyFlag, ...]:
        self.texts.append(text)
        if "web" in text:
            return self._flags
        return ()


class ReportingSupport(SourceSupportPort):
    def verify(self, draft: str, snippets: tuple[Snippet, ...]) -> SourceSupportReport:
        return Samples().support()


class RecordingModel(ScriptedLanguageModel):
    """A scripted model that counts its calls."""

    def __init__(self, text: str = "Hola means hello.") -> None:
        super().__init__(text, "a" * 64, Samples().decoding())
        self.calls = 0

    async def complete(self, prompt: RenderedPrompt) -> ModelCompletion:
        self.calls += 1
        return await super().complete(prompt)


class PromptEchoModel(RecordingModel):
    """A model whose completion is a digest of the exact prompt it was given.

    A constant completion reproduces whatever prompt a replay rebuilds, so it
    cannot show that replay rebuilt the same one. This one answers the same
    text only for the same rendered prompt, template version included.
    """

    async def complete(self, prompt: RenderedPrompt) -> ModelCompletion:
        self.calls += 1
        seen = f"{prompt.template_version}\n{prompt.text}".encode()
        return ModelCompletion(
            text=f"Echo {hashlib.sha256(seen).hexdigest()[:16]}.",
            model_revision=self.revision(),
            decoding_params=Samples().decoding(),
        )


class ScriptedGate(OversightGatePort):
    """A gate that returns one decision and counts its evaluations."""

    def __init__(self, decision: GateDecision, gate_name: str) -> None:
        self._decision = decision
        self._gate_name = gate_name
        self.calls = 0

    def name(self) -> str:
        return self._gate_name

    async def evaluate(self, turn: TurnState) -> GateVerdict:
        self.calls += 1
        return GateVerdict(
            gate_name=self._gate_name,
            decision=self._decision,
            reason=f"scripted {self._decision}",
            policy_rule_id=f"rule-{self._gate_name}-{self._decision}",
        )


class Agents:
    """A generation agent over stubs."""

    def generation(
        self,
        safety: SafetyClassifierPort | None = None,
        model: RecordingModel | None = None,
        template: PromptTemplatePort | None = None,
    ) -> ContentGenerationAgent:
        return ContentGenerationAgent(
            template if template is not None else FixedTemplate(),
            model if model is not None else RecordingModel(),
            FindingGrammar(),
            safety if safety is not None else FlaggingSafety(),
            ReportingSupport(),
            "This reply was generated by an AI tutor.",
        )
