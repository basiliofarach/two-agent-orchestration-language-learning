"""In-memory policy card returned by ``PolicyArtifactPort`` (REQ-POLICY)."""

from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ModelWrapValidatorHandler,
    field_validator,
    model_validator,
)


class MappedArticles:
    """The AI Act articles this prototype maps (REQ-MAP)."""

    def require(self, article: str) -> str:
        """Reject an article this prototype does not map."""
        if article not in self._accepted():
            msg = f"unknown article mapping: {article}"
            raise ValueError(msg)
        return article

    def _accepted(self) -> frozenset[str]:
        return frozenset({"10", "12", "14", "15"})


class PolicyRule(BaseModel):
    """One rule. ``policy_rule_id`` stays stable until the meaning changes.

    A column written before a rule carried its own id and article is a
    JSON string, the action. That string is both the id and the statement,
    because it was the only identity the row stored. The article was not
    on the action, so it stays unset: guessing one would write an AI Act
    mapping the payload never made. Assigning an article later changes
    the meaning and needs a new id.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_rule_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    article: str | None

    @model_validator(mode="wrap")
    @classmethod
    def accept_legacy_action(
        cls, value: object, handler: ModelWrapValidatorHandler["PolicyRule"]
    ) -> "PolicyRule":
        """Open a pre-object action string. A new rule still names an article."""
        if isinstance(value, str):
            return LegacyAction(action=value).rule()
        if isinstance(value, dict) and "article" not in value:
            msg = "policy rule has no article"
            raise ValueError(msg)
        return handler(value)

    @field_validator("article")
    @classmethod
    def article_is_mapped(cls, value: str | None) -> str | None:
        """Each new rule names the AI Act article it serves (REQ-MAP)."""
        if value is None:
            return None
        return MappedArticles().require(value)


class LegacyAction(BaseModel):
    """An action stored as a string, before a rule carried an id and an article.

    The string is the only identity the row stored, so it is both the id
    and the statement. The article was not on the action.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    action: str = Field(min_length=1)

    @model_validator(mode="after")
    def action_is_not_blank(self) -> Self:
        """A blank action is not a rule id."""
        if not self.action.strip():
            msg = "legacy policy action is empty"
            raise ValueError(msg)
        return self

    def rule(self) -> PolicyRule:
        """The stored string, with no article invented for it."""
        return PolicyRule(
            policy_rule_id=self.action,
            statement=self.action,
            article=None,
        )


class ArticleMapping(BaseModel):
    """One AI Act article and the locus in this prototype that carries it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    article: str = Field(min_length=1)
    locus: str = Field(min_length=1)

    @field_validator("article")
    @classmethod
    def article_is_mapped(cls, value: str) -> str:
        """An article outside REQ-MAP is not a mapping this card may name."""
        return MappedArticles().require(value)


class PolicyCard(BaseModel):
    """Versioned allowed actions, denials, escalation, and article mappings.

    ``version`` is the string written to ``turn_audit.policy_version``.
    The card is frozen: the port that returns it exposes no mutating method.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = Field(min_length=1)
    allowed_actions: tuple[PolicyRule, ...]
    denied_actions: tuple[PolicyRule, ...]
    escalation_rules: tuple[PolicyRule, ...]
    article_mappings: tuple[ArticleMapping, ...]

    def rules(self) -> tuple[PolicyRule, ...]:
        """Every rule on the card, in declaration order."""
        return self.allowed_actions + self.denied_actions + self.escalation_rules

    @model_validator(mode="after")
    def rule_ids_are_unique(self) -> Self:
        """One ``policy_rule_id`` names one rule inside a version."""
        seen: set[str] = set()
        for rule in self.rules():
            if rule.policy_rule_id in seen:
                msg = f"policy_rule_id repeated: {rule.policy_rule_id}"
                raise ValueError(msg)
            seen.add(rule.policy_rule_id)
        return self
