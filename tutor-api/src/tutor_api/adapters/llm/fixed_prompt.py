"""Fixed prompt template. Formulation is an accuracy control (REQ-ACCURACY)."""

from tutor_core.domain.models.learner import LearnerHistorySnapshot
from tutor_core.domain.models.retrieval import RetrievalResult, Snippet
from tutor_core.domain.models.safety import RenderedPrompt
from tutor_core.domain.ports.prompt_template import PromptTemplatePort


class FixedPromptTemplate(PromptTemplatePort):
    """Role, context, proficiency, structure and tone, from constructor arguments.

    Learner text is placed in the task section only. Role, structure, tone
    and the disclosure constraint come from this template, not from the
    learner. ``template_version()`` is the identifier the audit log stores.
    """

    def __init__(
        self,
        version: str,
        role: str,
        structure: str,
        tone: str,
        disclosure: str,
    ) -> None:
        self._version = self._required("template version", version)
        self._role = self._required("role", role)
        self._structure = self._required("output structure", structure)
        self._tone = self._required("tone", tone)
        self._disclosure = self._required("disclosure", disclosure)

    def render(
        self,
        task: str,
        context: RetrievalResult,
        history: LearnerHistorySnapshot,
    ) -> RenderedPrompt:
        """Render the fixed sections around the task and the retrieved context."""
        text = "\n\n".join(
            (
                f"Role: {self._role}",
                f"Tone: {self._tone}",
                f"Output structure: {self._structure}",
                f"Disclosure: {self._disclosure}",
                f"Target proficiency: {self._proficiency(history)}",
                f"Prior outcomes: {self._outcomes(history)}",
                f"Retrieved context:\n{self._context(context)}",
                f"Task: {task}",
            )
        )
        return RenderedPrompt(text=text, template_version=self._version)

    def template_version(self) -> str:
        """The version written into the audit record."""
        return self._version

    def _proficiency(self, history: LearnerHistorySnapshot) -> str:
        if history.proficiency_level is None:
            return "not on record"
        return history.proficiency_level

    def _outcomes(self, history: LearnerHistorySnapshot) -> str:
        if history.events is None:
            return "not on record"
        if not history.events:
            return "none admitted"
        lines = tuple(
            f"{item.item_id}: {'correct' if item.correct else 'incorrect'}"
            for item in history.events
        )
        return "; ".join(lines)

    def _context(self, context: RetrievalResult) -> str:
        if not context.snippets:
            return "none"
        return "\n".join(self._snippet(snippet) for snippet in context.snippets)

    def _snippet(self, snippet: Snippet) -> str:
        source = snippet.source
        return (
            f"[{source.source_uri} version {source.version}, "
            f"{source.review_status}] {snippet.content}"
        )

    def _required(self, label: str, value: str) -> str:
        if not value.strip():
            msg = f"{label} is empty"
            raise ValueError(msg)
        return value
