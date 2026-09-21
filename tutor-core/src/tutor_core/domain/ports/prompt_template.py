"""Fixed prompt templates. Formulation is an accuracy control."""

from abc import ABC, abstractmethod

from tutor_core.domain.models.learner import LearnerHistorySnapshot
from tutor_core.domain.models.retrieval import RetrievalResult
from tutor_core.domain.models.safety import RenderedPrompt


class PromptTemplatePort(ABC):
    """Build structured prompts and carry tone constraints (REQ-ACCURACY, REQ-MINOR).

    Scope boundary: fixed templates only. ``template_version()`` is the
    identifier written into the audit record. Role, retrieved context,
    target proficiency, output structure, and tone come from the template,
    not from free-form learner input.
    """

    @abstractmethod
    def render(
        self,
        task: str,
        context: RetrievalResult,
        history: LearnerHistorySnapshot,
    ) -> RenderedPrompt:
        """Render the fixed template for this task, context, and history."""
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    def template_version(self) -> str:
        """Return the template version to log with the turn."""
        raise NotImplementedError  # pragma: no cover
