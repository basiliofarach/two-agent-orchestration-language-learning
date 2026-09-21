"""Prompt in, completion out. No tools and no network."""

from abc import ABC, abstractmethod

from tutor_core.domain.models.safety import ModelCompletion, RenderedPrompt


class LanguageModelPort(ABC):
    """Turn a rendered prompt into a completion (REQ-COMP).

    Scope boundary: no tool access and no network. The port exposes
    ``complete()`` and ``revision()`` only — no retriever, no HTTP client,
    no tool registry — so a prompt-injected instruction to fetch external
    content has nothing to reach.
    """

    @abstractmethod
    def complete(self, prompt: RenderedPrompt) -> ModelCompletion:
        """Generate from ``prompt`` and return the completion."""
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    def revision(self) -> str:
        """Return the pinned model revision written into the audit record."""
        raise NotImplementedError  # pragma: no cover
