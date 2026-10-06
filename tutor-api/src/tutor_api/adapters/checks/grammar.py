"""Grammar findings. The check reports; it does not rewrite the draft."""

import re

from pydantic import BaseModel, ConfigDict, Field

from tutor_core.domain.models.safety import GrammarFinding
from tutor_core.domain.ports.grammar_check import GrammarCheckPort


class GrammarPattern(BaseModel):
    """One expression, the finding it reports, and an optional suggestion."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pattern: str = Field(min_length=1)
    message: str = Field(min_length=1)
    replacement: str | None = None


class PatternGrammarCheck(GrammarCheckPort):
    """Report matches. The draft string is not returned and not edited."""

    def __init__(self, patterns: tuple[GrammarPattern, ...]) -> None:
        self._patterns = patterns

    def check(self, text: str) -> tuple[GrammarFinding, ...]:
        """Return one finding per match, in pattern order then match order."""
        findings: list[GrammarFinding] = []
        for pattern in self._patterns:
            for match in re.finditer(pattern.pattern, text):
                findings.append(
                    GrammarFinding(
                        message=pattern.message,
                        offset=match.start(),
                        length=len(match.group(0)),
                        replacement=pattern.replacement,
                    )
                )
        return tuple(findings)


class MinorGrammarPatterns:
    """A small deterministic set for the prototype. Not a language-tool server.

    Replay has to be stable, so the check is a pattern rather than a
    service whose version would move (REQ-COMP).
    """

    def patterns(self) -> tuple[GrammarPattern, ...]:
        """Agreement errors a tutor would expect the check to notice."""
        return (
            GrammarPattern(
                pattern=r"\b[Hh]e go\b",
                message="The verb does not agree with 'he'.",
                replacement="he goes",
            ),
            GrammarPattern(
                pattern=r"\b[Ss]he go\b",
                message="The verb does not agree with 'she'.",
                replacement="she goes",
            ),
        )
