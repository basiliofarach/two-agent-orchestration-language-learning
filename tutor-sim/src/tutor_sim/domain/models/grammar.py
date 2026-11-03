"""CEFR-SP sentences, Grammar Profile items, and a tagged sentence."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tutor_sim.domain.models.kb import CefrLevel

CefrSpSubset = Literal["wiki-auto", "score"]


class CefrSpRow(BaseModel):
    """One raw CEFR-SP row, before agreement is checked."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sentence_id: str = Field(min_length=1)
    text: str
    level_a: str
    level_b: str
    subset: str


class GrammarProfileRow(BaseModel):
    """One raw Grammar Profile row, before the sub-level is mapped."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    item_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    cefr_j_level: str = Field(min_length=1)
    pattern: str = Field(min_length=1)
    regex: str = Field(min_length=1)


class CefrSpSentence(BaseModel):
    """One sentence both annotators placed at the same A1–B2 level."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sentence_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    level: CefrLevel
    subset: CefrSpSubset
    licence: str = Field(min_length=1)

    @model_validator(mode="after")
    def text_is_a_sentence(self) -> "CefrSpSentence":
        """Whitespace is not a sentence."""
        if not self.text.strip():
            msg = "sentence is blank"
            raise ValueError(msg)
        return self


class GrammarItem(BaseModel):
    """One teachers'-sheet item and the regex that finds its examples."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    item_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    cefr_j_level: str = Field(min_length=1)
    band: CefrLevel
    pattern: str = Field(min_length=1)
    regex: str = Field(min_length=1)


class TaggedToken(BaseModel):
    """One token in the Grammar Profile's ``word_TAG_lemma`` form."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    word: str = Field(min_length=1)
    tag: str = Field(min_length=1)
    lemma: str = Field(min_length=1)


class TaggedSentence(BaseModel):
    """A sentence and the tagger output a Grammar Profile regex searches."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=1)
    tokens: tuple[TaggedToken, ...] = Field(min_length=1)

    def profile_line(self) -> str:
        """The single line the item regex is applied to."""
        return " ".join(
            f"{token.word}_{token.tag}_{token.lemma}" for token in self.tokens
        )


class GrammarExample(BaseModel):
    """One CEFR-SP sentence mined for one grammar item."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    item_id: str = Field(min_length=1)
    sentence: CefrSpSentence


class LevelItemCount(BaseModel):
    """How many grammar items a build placed at one band."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    level: CefrLevel
    count: int = Field(ge=0)


class ItemCountLog(BaseModel):
    """The build log of grammar-item counts. Measures read this, not the seed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    counts: tuple[LevelItemCount, ...]


class WordLevel(BaseModel):
    """One content word and the easiest CEFR-J level that lists it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    word: str = Field(min_length=1)
    level: CefrLevel
