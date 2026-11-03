"""Tag sentences for Grammar Profile regexes. The system never tags."""

import hashlib
import re
import subprocess
from pathlib import Path

from tutor_sim.domain.models.grammar import TaggedSentence, TaggedToken
from tutor_sim.domain.ports.pos_tagger import PosTaggerPort


class UntaggedSentence(ValueError):
    """The fixture has no tags for this sentence."""


class TaggingFailed(ValueError):
    """TreeTagger did not return one token line per word."""


class FixtureTagger(PosTaggerPort):
    """Pre-tagged sentences. Tests and the property check use this."""

    def __init__(self, tagged: dict[str, TaggedSentence], revision_label: str) -> None:
        self._tagged = tagged
        self._revision = revision_label

    def revision(self) -> str:
        """The label recorded on a fixture build."""
        return self._revision

    def tag(self, sentence: str) -> TaggedSentence:
        """Return the prepared tags. An unknown sentence fails the build."""
        found = self._tagged.get(sentence)
        if found is None:
            msg = f"no fixture tags for {sentence}"
            raise UntaggedSentence(msg)
        return found


class PinnedBytes:
    """A file whose bytes match a recorded sha256."""

    def __init__(self, path: Path, expected_sha256: str) -> None:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected_sha256:
            msg = f"{path.name} is not the pinned file"
            raise TaggingFailed(msg)
        self._path = path

    def path(self) -> Path:
        """The checked path."""
        return self._path


class TreeTaggerTokens:
    """Split a sentence the way TreeTagger's English tokenizer does.

    The core binary reads one token per line and does not tokenize. The
    English parameter file was trained on Penn-style tokens, so clitics are
    their own tokens (``do n't``, ``Ada 's``) and punctuation stands alone.
    """

    _TOKEN = re.compile(
        r"[^\W\d_]+(?=n't\b)"  # "do" of "don't"
        r"|n't\b"
        r"|'(?:s|re|ve|ll|d|m)\b"
        r"|\d+(?:[.,]\d+)*"
        r"|\w+(?:-\w+)*"
        r"|[^\w\s]",
        re.IGNORECASE,
    )

    def split(self, sentence: str) -> tuple[str, ...]:
        """The tokens in order. Whitespace is not a token."""
        return tuple(self._TOKEN.findall(sentence))


class TreeTaggerProcess(PosTaggerPort):
    """Run the core TreeTagger binary on one token per line.

    ``-token -lemma`` makes each output line ``token tag lemma``; without
    them the binary prints the tag alone. ``-quiet`` drops progress output.
    """

    _OPTIONS = ("-token", "-lemma", "-quiet")

    def __init__(
        self,
        binary: PinnedBytes,
        parameters: PinnedBytes,
        version: str,
        tokens: TreeTaggerTokens,
    ) -> None:
        self._binary = binary
        self._parameters = parameters
        self._version = version
        self._tokens = tokens

    def revision(self) -> str:
        """The pinned TreeTagger version, not a floating tag."""
        return self._version

    def tag(self, sentence: str) -> TaggedSentence:
        """Tag one sentence. A non-zero exit fails the build."""
        tokens = self._tokens.split(sentence)
        completed = subprocess.run(
            [
                str(self._binary.path()),
                *self._OPTIONS,
                str(self._parameters.path()),
            ],
            input="".join(f"{token}\n" for token in tokens),
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            msg = completed.stderr or "tree-tagger failed"
            raise TaggingFailed(msg)
        return self._parse(sentence, completed.stdout)

    def _parse(self, sentence: str, output: str) -> TaggedSentence:
        tokens: list[TaggedToken] = []
        for line in output.splitlines():
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) != 3:
                msg = f"tree-tagger line is not word tag lemma: {line}"
                raise TaggingFailed(msg)
            tokens.append(TaggedToken(word=parts[0], tag=parts[1], lemma=parts[2]))
        if not tokens:
            msg = f"tree-tagger returned no tokens for {sentence}"
            raise TaggingFailed(msg)
        return TaggedSentence(text=sentence, tokens=tuple(tokens))
