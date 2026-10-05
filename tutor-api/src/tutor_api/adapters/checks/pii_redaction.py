"""Redact PII before any agent or the audit log sees learner text."""

import re
from functools import partial

from pydantic import BaseModel, ConfigDict, Field

from tutor_core.domain.models.safety import RedactedText
from tutor_core.domain.ports.pii_redaction import PiiRedactionPort


class RedactionFailed(Exception):
    """Redaction did not complete. The original text is not returned."""


class RedactionStep(BaseModel):
    """One category and the expression that finds it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    category: str = Field(min_length=1)
    pattern: str = Field(min_length=1)


class StandardPiiSteps:
    """Email, phone, a stated name, and a street address, in English and Spanish.

    Nothing here calls a language model. Redaction has to run when the
    model is down (REQ-MINOR).

    Pattern-based, so it finds stated forms only. A name with no lead-in
    ("Ada is my friend") is not found. Where a form is ambiguous the
    pattern over-redacts: a capitalised word after "I am" is treated as a
    name. For a minor's input, a lost word costs less than a leaked name.
    """

    _UPPER = "A-ZÀ-ÖØ-Þ"
    _LOWER = "a-zß-öø-ÿ"

    def steps(self) -> tuple[RedactionStep, ...]:
        """The categories ``RegexPiiRedactor`` removes, in order."""
        return (
            RedactionStep(
                category="email",
                pattern=r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",
            ),
            RedactionStep(category="phone", pattern=self._phone()),
            RedactionStep(category="person_name", pattern=self._person_name()),
            RedactionStep(category="postal_address", pattern=self._address()),
        )

    def _phone(self) -> str:
        return (
            r"(?<!\w)\+\d{1,3}(?:[\s.\-]\d{2,4}){2,}(?!\w)"
            r"|(?<!\w)\(\d{2,4}\)\s?\d{3}[\s.\-]?\d{3,4}(?!\w)"
            r"|\b\d{3}[\s.\-]\d{3}[\s.\-]\d{3,4}\b"
            r"|\b\d{2,3}(?:[\s.\-]\d{2,3}){3}\b"
            r"|\b\d{9,15}\b"
        )

    def _person_name(self) -> str:
        word = f"[{self._UPPER}][{self._LOWER}]+"
        lead_in = (
            r"(?i:\b(?:my\s+name\s+is|my\s+name['’]s|i['’]m|i\s+am|call\s+me"
            r"|me\s+llamo|mi\s+nombre\s+es|soy)\s+)"
        )
        return rf"{lead_in}(?P<pii>{word}(?:\s+{word}){{0,2}})\b"

    def _address(self) -> str:
        word = f"[{self._UPPER}][{self._LOWER}]+"
        joiner = r"(?:(?:de|del|la|las|los|el)\s+)?"
        english = (
            rf"\b\d{{1,5}}\s+(?:{word}\s+){{1,4}}"
            r"(?:Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Drive|Dr|Boulevard|Blvd)\b\.?"
        )
        spanish = (
            r"\b(?:[Cc]alle|C/|[Aa]venida|Avda\.?|[Pp]laza|[Pp]aseo)\s*"
            rf"{joiner}{word}(?:\s+{joiner}{word})*,?\s*(?:n[º°o]\.?\s*)?\d{{1,5}}\b"
        )
        return f"{english}|{spanish}"


class RegexPiiRedactor(PiiRedactionPort):
    """Replace each matched category with a token (REQ-MINOR).

    When a pattern names a ``pii`` group, only that group is replaced, so
    "My name is Ada" keeps "My name is" for the tutor. Otherwise the whole
    match is replaced.

    A failure raises ``RedactionFailed``. The input is not returned
    unchanged: fail closed, before any audit write.
    """

    def __init__(self, steps: tuple[RedactionStep, ...]) -> None:
        self._steps = steps

    def redact(self, text: str) -> RedactedText:
        """Return the redacted text, the categories removed, and the count."""
        try:
            return self._apply(text)
        except Exception as exc:
            raise RedactionFailed("redaction failed closed") from exc

    def _apply(self, text: str) -> RedactedText:
        categories: list[str] = []
        count = 0
        current = text
        for step in self._steps:
            replace = partial(self._replace, token=self._token(step.category))
            current, found = re.compile(step.pattern).subn(replace, current)
            count += found
            if found:
                categories.append(step.category)
        return RedactedText(
            text=current,
            redacted_categories=tuple(categories),
            redaction_count=count,
        )

    def _replace(self, match: re.Match[str], token: str) -> str:
        if "pii" not in match.re.groupindex:
            return token
        whole = match.group(0)
        start = match.start("pii") - match.start()
        end = match.end("pii") - match.start()
        return whole[:start] + token + whole[end:]

    def _token(self, category: str) -> str:
        return f"[REDACTED:{category}]"
