"""PII is removed at the boundary, and a failure does not pass the text through."""

import inspect
from pathlib import Path

import pytest
from tests.contract.test_port_contracts import PiiRedactionPortContract

from tutor_api.adapters.checks.pii_redaction import (
    RedactionFailed,
    RedactionStep,
    RegexPiiRedactor,
    StandardPiiSteps,
)
from tutor_core.domain.ports.pii_redaction import PiiRedactionPort


class PiiExamples:
    """One raw string per form, and the secret that must not survive."""

    def cases(self) -> tuple[tuple[str, str, str], ...]:
        return (
            ("email", "Email ada@example.com please", "ada@example.com"),
            ("phone", "Call +34 612 345 678 today", "+34 612 345 678"),
            ("phone", "Call 612-345-6789 today", "612-345-6789"),
            ("phone", "Call (555) 123-4567 today", "(555) 123-4567"),
            ("phone", "Llama al 612 345 678", "612 345 678"),
            ("phone", "Mi número es 912 34 56 78", "912 34 56 78"),
            ("phone", "Text 5551234567 now", "5551234567"),
            ("person_name", "My name is Ada Lovelace", "Ada Lovelace"),
            ("person_name", "I'm Ada Lovelace", "Ada Lovelace"),
            ("person_name", "I’m Ada", "Ada"),
            ("person_name", "I am Bob", "Bob"),
            ("person_name", "call me Bob", "Bob"),
            ("person_name", "Me llamo Ana García", "Ana García"),
            ("person_name", "mi nombre es Lucía", "Lucía"),
            ("person_name", "Hola, soy Íñigo", "Íñigo"),
            ("postal_address", "I live at 12 King Street", "12 King Street"),
            ("postal_address", "I live at 12 Baker St", "12 Baker St"),
            ("postal_address", "Vivo en la Calle Mayor 5", "Calle Mayor 5"),
            ("postal_address", "Vivo en Avenida de América, 10", "América, 10"),
        )


class OrdinaryPrompts:
    """Learner text with no PII. A lead-in phrase alone is not a name."""

    def cases(self) -> tuple[str, ...]:
        return (
            "Where is the library?",
            "my name is going to be on the list",
            "I am tired",
            "I'm going to the library",
            "Soy estudiante",
            "Call me tomorrow",
            "I have 3 cats and 2 dogs",
            "The year 2026 was good",
        )


class TestRegexPiiRedactorContract(PiiRedactionPortContract):
    def port(self) -> PiiRedactionPort:
        return RegexPiiRedactor(StandardPiiSteps().steps())


class TestRegexPiiRedactor:
    @pytest.mark.parametrize(
        ("category", "raw", "secret"),
        PiiExamples().cases(),
    )
    def test_each_category_is_removed(
        self, category: str, raw: str, secret: str
    ) -> None:
        redacted = RegexPiiRedactor(StandardPiiSteps().steps()).redact(raw)
        assert category in redacted.redacted_categories
        assert secret not in redacted.text
        assert f"[REDACTED:{category}]" in redacted.text
        assert redacted.redaction_count >= 1

    @pytest.mark.parametrize("raw", OrdinaryPrompts().cases())
    def test_a_prompt_with_no_pii_is_unchanged(self, raw: str) -> None:
        redacted = RegexPiiRedactor(StandardPiiSteps().steps()).redact(raw)
        assert redacted.text == raw
        assert redacted.redacted_categories == ()
        assert redacted.redaction_count == 0

    def test_the_lead_in_phrase_is_kept_for_the_tutor(self) -> None:
        redacted = RegexPiiRedactor(StandardPiiSteps().steps()).redact(
            "My name is Ada and I like books"
        )
        assert redacted.text == "My name is [REDACTED:person_name] and I like books"

    def test_repeated_emails_count_each_match(self) -> None:
        redacted = RegexPiiRedactor(StandardPiiSteps().steps()).redact(
            "ada@example.com and bob@example.com"
        )
        assert redacted.redacted_categories == ("email",)
        assert redacted.redaction_count == 2

    def test_a_redactor_failure_raises_rather_than_returning_the_input(self) -> None:
        redactor = RegexPiiRedactor((RedactionStep(category="email", pattern="("),))
        with pytest.raises(RedactionFailed, match="failed closed") as raised:
            redactor.redact("ada@example.com")
        assert raised.value.__cause__ is not None

    def test_redaction_does_not_depend_on_the_language_model(self) -> None:
        location = inspect.getsourcefile(RegexPiiRedactor)
        assert location is not None
        source = Path(location).read_text(encoding="utf-8")
        assert "LanguageModelPort" not in source
        assert "ollama" not in source.lower()

    def test_public_methods_are_redact_only(self) -> None:
        public = [
            name
            for name in dir(RegexPiiRedactor)
            if not name.startswith("_") and callable(getattr(RegexPiiRedactor, name))
        ]
        assert public == ["redact"]
