"""In-memory policy card returned by ``PolicyArtifactPort`` (REQ-POLICY)."""

from pydantic import BaseModel, ConfigDict, Field


class ArticleMapping(BaseModel):
    """One AI Act article and the locus in this prototype that carries it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    article: str = Field(min_length=1)
    locus: str = Field(min_length=1)


class PolicyCard(BaseModel):
    """Versioned allowed actions, denials, escalation, and article mappings.

    ``version`` is the string written to ``turn_audit.policy_version``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = Field(min_length=1)
    allowed_actions: tuple[str, ...]
    denied_actions: tuple[str, ...]
    escalation_rules: tuple[str, ...]
    article_mappings: tuple[ArticleMapping, ...]
