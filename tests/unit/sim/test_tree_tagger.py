"""TreeTagger is a pinned local process. A bad pin or a bad line fails the build."""

import hashlib
import stat
from pathlib import Path

import pytest

from tutor_sim.adapters.pos_tagger import (
    PinnedBytes,
    TaggingFailed,
    TreeTaggerProcess,
    TreeTaggerTokens,
)

# The core binary: options, then the parameter file. One token per stdin line;
# with -token -lemma each output line is ``token<TAB>tag<TAB>lemma``. Without
# both options it prints the tag alone, which is what this fake does too.
_CORE = """#!/bin/sh
if [ "$1" != "-token" ] || [ "$2" != "-lemma" ] || [ ! -f "$4" ]; then
  while IFS= read -r token; do printf 'XX\\n'; done
  exit 0
fi
while IFS= read -r token; do
  printf '%s\\tXX\\t%s\\n' "$token" "$token"
done
"""


class FakeBinary:
    def place(self, directory: Path, script: str) -> tuple[PinnedBytes, PinnedBytes]:
        binary = directory / "tagger"
        parameters = directory / "english.par"
        binary.write_text(script, encoding="utf-8")
        parameters.write_text("parameters\n", encoding="utf-8")
        binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
        return (
            PinnedBytes(binary, self._sha(binary)),
            PinnedBytes(parameters, self._sha(parameters)),
        )

    def _sha(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()


class TestTreeTagger:
    def test_a_token_line_becomes_a_profile_sentence(self, tmp_path: Path) -> None:
        binary, parameters = FakeBinary().place(
            tmp_path,
            "#!/bin/sh\nprintf '\\ncats NN cat\\n'\n",
        )
        tagger = TreeTaggerProcess(binary, parameters, "3.2.5", TreeTaggerTokens())
        tagged = tagger.tag("cats")
        assert tagger.revision() == "3.2.5"
        assert tagged.profile_line() == "cats_NN_cat"

    def test_the_core_binary_gets_one_token_per_line_and_the_options(
        self, tmp_path: Path
    ) -> None:
        binary, parameters = FakeBinary().place(tmp_path, _CORE)
        tagged = TreeTaggerProcess(binary, parameters, "3.2.5", TreeTaggerTokens()).tag(
            "The cat sits."
        )
        assert tagged.profile_line() == "The_XX_The cat_XX_cat sits_XX_sits ._XX_."

    def test_a_wrong_pin_or_a_bad_run_is_refused(self, tmp_path: Path) -> None:
        binary = tmp_path / "tagger"
        binary.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
        parameters = tmp_path / "english.par"
        parameters.write_text("parameters\n", encoding="utf-8")
        digest = hashlib.sha256(parameters.read_bytes()).hexdigest()
        with pytest.raises(TaggingFailed, match="not the pinned file"):
            PinnedBytes(binary, "ab" * 32)
        pinned_parameters = PinnedBytes(parameters, digest)
        pinned_binary = PinnedBytes(
            binary, hashlib.sha256(binary.read_bytes()).hexdigest()
        )
        with pytest.raises(TaggingFailed, match="failed"):
            TreeTaggerProcess(
                pinned_binary, pinned_parameters, "3.2.5", TreeTaggerTokens()
            ).tag("cats")

    def test_a_line_that_is_not_three_fields_is_refused(self, tmp_path: Path) -> None:
        binary, parameters = FakeBinary().place(
            tmp_path, "#!/bin/sh\nprintf 'only two\\n'\n"
        )
        with pytest.raises(TaggingFailed, match="word tag lemma"):
            TreeTaggerProcess(binary, parameters, "3.2.5", TreeTaggerTokens()).tag(
                "cats"
            )

    def test_empty_output_is_refused(self, tmp_path: Path) -> None:
        binary, parameters = FakeBinary().place(tmp_path, "#!/bin/sh\nprintf '\\n'\n")
        with pytest.raises(TaggingFailed, match="no tokens"):
            TreeTaggerProcess(binary, parameters, "3.2.5", TreeTaggerTokens()).tag(
                "cats"
            )


class TestTreeTaggerTokens:
    def test_words_punctuation_and_clitics_split_as_treetagger_expects(
        self,
    ) -> None:
        tokens = TreeTaggerTokens().split("I don't think it's Ada's, OK?")
        assert tokens == (
            "I",
            "do",
            "n't",
            "think",
            "it",
            "'s",
            "Ada",
            "'s",
            ",",
            "OK",
            "?",
        )

    def test_numbers_and_hyphenated_words_stay_whole(self) -> None:
        assert TreeTaggerTokens().split("A well-known 3.5 km walk.") == (
            "A",
            "well-known",
            "3.5",
            "km",
            "walk",
            ".",
        )

    def test_blank_text_has_no_tokens(self) -> None:
        assert TreeTaggerTokens().split("   ") == ()
