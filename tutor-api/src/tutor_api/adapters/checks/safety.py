"""Safety flags. A flag is a fact about the text, not a gate verdict."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tutor_core.domain.models.safety import SafetyFlag
from tutor_core.domain.ports.safety_classifier import SafetyClassifierPort


class SafetyRule(BaseModel):
    """One category the classifier may raise. Patterns come from construction."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    category: str = Field(min_length=1)
    pattern: str = Field(min_length=1)
    severity: Literal["low", "medium", "high"]
    message: str = Field(min_length=1)


class CategorySafetyClassifier(SafetyClassifierPort):
    """Flag matches. Do not remove text and do not decide a gate verdict.

    An empty rule set is rejected: a classifier with no rules would pass
    every draft, which is fail-open for a minor learner (REQ-COMP).
    """

    def __init__(self, rules: tuple[SafetyRule, ...]) -> None:
        if not rules:
            msg = "safety classifier has no rules"
            raise ValueError(msg)
        # Patterns are written in lowercase. Matching is case-insensitive so
        # "Search the web" and "Diagnose" still flag (REQ-COMP). An invalid
        # pattern fails here, at construction, rather than passing every draft.
        compiled: list[tuple[SafetyRule, re.Pattern[str]]] = []
        for rule in rules:
            try:
                pattern = re.compile(rule.pattern, re.IGNORECASE)
            except re.error as exc:
                msg = "safety rule pattern is not a regular expression"
                raise ValueError(msg) from exc
            compiled.append((rule, pattern))
        self._compiled = tuple(compiled)

    def classify(self, text: str) -> tuple[SafetyFlag, ...]:
        """Return one flag per matching rule, in rule order."""
        flags: list[SafetyFlag] = []
        for rule, pattern in self._compiled:
            if pattern.search(text) is not None:
                flags.append(
                    SafetyFlag(
                        category=rule.category,
                        message=rule.message,
                        severity=rule.severity,
                    )
                )
        return tuple(flags)


class MinorSafetyRules:
    """Out-of-scope, unsafe, and proficiency cues for this prototype."""

    def rules(self) -> tuple[SafetyRule, ...]:
        """High severity refuses. Proficiency is flagged and not a refusal."""
        return (
            SafetyRule(
                category="out_of_scope",
                pattern=r"search the (web|internet)|look (it |this )?up online",
                severity="high",
                message="This asks for the open web, which this tutor cannot use.",
            ),
            SafetyRule(
                category="unsafe",
                pattern=r"\bdiagnos(e|is)\b|\bprescription\b",
                severity="high",
                message="This asks for medical advice a language tutor does not give.",
            ),
            SafetyRule(
                category="proficiency",
                pattern=r"\byour level is\b|\btheir level is\b",
                severity="medium",
                message="This talks about an assessed proficiency level.",
            ),
            SafetyRule(
                category="prompt_injection",
                pattern=(
                    r"ignore (all |any )?(previous|prior) instructions"
                    r"|reveal your (system )?prompt"
                ),
                severity="high",
                message="This tries to change the tutor's instructions.",
            ),
        )
