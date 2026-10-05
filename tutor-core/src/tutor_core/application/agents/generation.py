"""Content Generation Agent. Fixed template, local model, checks, disclosure."""

from abc import ABC, abstractmethod

from tutor_core.domain.models.learner import LearnerHistorySnapshot
from tutor_core.domain.models.pipeline import GeneratedDraft
from tutor_core.domain.models.retrieval import RetrievalResult
from tutor_core.domain.models.safety import (
    GeneratedUnit,
    SafetyFlag,
    SourceSupportReport,
)
from tutor_core.domain.ports.grammar_check import GrammarCheckPort
from tutor_core.domain.ports.language_model import LanguageModelPort
from tutor_core.domain.ports.prompt_template import PromptTemplatePort
from tutor_core.domain.ports.safety_classifier import SafetyClassifierPort
from tutor_core.domain.ports.source_support import SourceSupportPort


class GenerationAgent(ABC):
    """Generate from retrieved context. Not a DEC-0001 port.

    The agent holds the template, the model and the three checks. It
    holds no retriever (REQ-COMP).
    """

    @abstractmethod
    async def generate(
        self,
        task: str,
        context: RetrievalResult,
        history: LearnerHistorySnapshot,
    ) -> GeneratedDraft:
        """Render, complete, check, and attach the disclosure."""
        raise NotImplementedError  # pragma: no cover


class ContentGenerationAgent(GenerationAgent):
    """Assemble the fixed template, generate, check, disclose, or refuse.

    Disclosure is a constructor argument and is set on every unit,
    including a refusal. There is no switch that omits it (REQ-MINOR).

    A high-severity flag on the task refuses before the model is called.
    That refusal has no model output: ``output_before_checks`` is ``None``
    and no template version, revision or decoding is recorded, because none
    was used. Checks report and do not replace the draft:
    ``output_after_checks`` is the same text as ``output_before_checks``.
    A high-severity flag on the draft refuses, and the draft stays so a
    tutor can see it.
    """

    def __init__(
        self,
        template: PromptTemplatePort,
        model: LanguageModelPort,
        grammar: GrammarCheckPort,
        safety: SafetyClassifierPort,
        support: SourceSupportPort,
        disclosure: str,
    ) -> None:
        if not disclosure.strip():
            msg = "ai disclosure is empty"
            raise ValueError(msg)
        self._template = template
        self._model = model
        self._grammar = grammar
        self._safety = safety
        self._support = support
        self._disclosure = disclosure

    async def generate(
        self,
        task: str,
        context: RetrievalResult,
        history: LearnerHistorySnapshot,
    ) -> GeneratedDraft:
        """Return a draft with disclosure, or a refusal that did not edit text."""
        flagged = self._safety.classify(task)
        if self._high(flagged):
            return self._refused(flagged, self._reason(flagged))
        rendered = self._template.render(task, context, history)
        completion = await self._model.complete(rendered)
        draft = completion.text
        findings = self._grammar.check(draft)
        draft_flags = self._safety.classify(draft)
        report = self._support.verify(draft, context.snippets)
        refused = self._high(draft_flags)
        unit = GeneratedUnit(
            output_before_checks=draft,
            output_after_checks=draft,
            ai_disclosure=self._disclosure,
            refused=refused,
            refusal_reason=self._reason(draft_flags) if refused else None,
            support=report,
            grammar=findings,
        )
        return GeneratedDraft(
            unit=unit,
            safety_flags=draft_flags,
            template_version=rendered.template_version,
            model_revision=completion.model_revision,
            decoding_params=completion.decoding_params,
        )

    def _refused(self, flags: tuple[SafetyFlag, ...], reason: str) -> GeneratedDraft:
        """A refusal before the model ran. There is no model output to record."""
        unit = GeneratedUnit(
            output_before_checks=None,
            output_after_checks=reason,
            ai_disclosure=self._disclosure,
            refused=True,
            refusal_reason=reason,
            support=SourceSupportReport(
                supported=(), unsupported=(), support_ratio=1.0
            ),
            grammar=(),
        )
        return GeneratedDraft(unit=unit, safety_flags=flags)

    def _high(self, flags: tuple[SafetyFlag, ...]) -> bool:
        return any(flag.severity == "high" for flag in flags)

    def _reason(self, flags: tuple[SafetyFlag, ...]) -> str:
        return " ".join(flag.message for flag in flags if flag.severity == "high")
