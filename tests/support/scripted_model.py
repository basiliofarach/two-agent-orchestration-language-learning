"""A language model that returns a scripted completion. For deterministic tests."""

from tutor_core.domain.models.safety import (
    DecodingParams,
    ModelCompletion,
    RenderedPrompt,
)
from tutor_core.domain.ports.language_model import LanguageModelPort


class ScriptedLanguageModel(LanguageModelPort):
    """``complete`` returns the text it was given. ``revision`` is the pinned SHA.

    No retriever and no HTTP client. Tests substitute this for
    ``OllamaLanguageModel`` so a scenario does not depend on a running model.
    """

    def __init__(self, text: str, revision: str, decoding: DecodingParams) -> None:
        if not revision.strip():
            msg = "model revision is empty"
            raise ValueError(msg)
        self._text = text
        self._revision = revision
        self._decoding = decoding

    async def complete(self, prompt: RenderedPrompt) -> ModelCompletion:
        """Return the scripted completion and the revision this stub was given."""
        return ModelCompletion(
            text=self._text,
            model_revision=self.revision(),
            decoding_params=self._decoding,
        )

    def revision(self) -> str:
        """The SHA written into the audit record."""
        return self._revision
