"""Tag a sentence for a Grammar Profile regex. The system never tags."""

from abc import ABC, abstractmethod

from tutor_sim.domain.models.grammar import TaggedSentence


class PosTaggerPort(ABC):
    """``word_TAG_lemma`` for one sentence. Harness-side only."""

    @abstractmethod
    def revision(self) -> str:
        """The pinned tagger revision recorded on the build."""
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    def tag(self, sentence: str) -> TaggedSentence:
        """Tag ``sentence``. The same sentence tags the same way."""
        raise NotImplementedError  # pragma: no cover
