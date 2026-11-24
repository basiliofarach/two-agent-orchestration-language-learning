"""Level fit, pupil level and target structure of one run (SIMULATION §9.5).

No text is kept. A measured text is named by its case or turn and carries
only numbers: what share of its CEFR-J-listed words sit at or below the
persona's level, and whether an I2 exercise matched its grammar item.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tutor_sim.domain.models.persona import PupilLevel

TextKind = Literal["reply", "pupil"]


class MeasuredText(BaseModel):
    """One text, measured and then dropped.

    ``coverage`` is ``None`` when the text has no word the CEFR-J wordlist
    lists. ``target_present`` is set only for a released I2 exercise.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    text_id: str = Field(min_length=1)
    kind: TextKind
    persona_level: PupilLevel
    intent: str | None = None
    listed_words: int = Field(ge=0)
    coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    target_item_id: str | None = None
    target_present: bool | None = None

    @model_validator(mode="after")
    def _coverage_needs_words(self) -> "MeasuredText":
        if (self.coverage is None) != (self.listed_words == 0):
            msg = "coverage is set exactly when a listed word was found"
            raise ValueError(msg)
        if (self.target_item_id is None) != (self.target_present is None):
            msg = "a target item and its result are set together"
            raise ValueError(msg)
        return self


class CoverageSummary(BaseModel):
    """Coverage at the persona's level, over one level or all (``None``).

    Quantiles are nearest-rank, so each is a coverage some text had.
    ``at_95`` and ``at_98`` count texts at or above that share.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: TextKind
    level: PupilLevel | None = None
    n: int = Field(ge=0)
    unscored: int = Field(ge=0)
    p10: float | None = None
    p25: float | None = None
    p50: float | None = None
    p75: float | None = None
    p90: float | None = None
    at_95: int = Field(ge=0)
    at_98: int = Field(ge=0)

    @model_validator(mode="after")
    def _counts_within_n(self) -> "CoverageSummary":
        if self.at_98 > self.at_95 or self.at_95 > self.n:
            msg = "at_98 <= at_95 <= n"
            raise ValueError(msg)
        return self


class TargetStructureRow(BaseModel):
    """Released I2 exercises matching their item's regex, ``k/n``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    level: PupilLevel | None = None
    k: int = Field(ge=0)
    n: int = Field(ge=0)

    @model_validator(mode="after")
    def _k_within_n(self) -> "TargetStructureRow":
        if self.k > self.n:
            msg = "k cannot exceed n"
            raise ValueError(msg)
        return self


class RunMeasures(BaseModel):
    """``runs/<run_id>/measures.json``. Written once; never rewritten.

    ``unreadable`` counts Tier 1 replies the API no longer returned, so a
    measure over fewer texts than the run released says why.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(min_length=1)
    tier: Literal["1", "2"]
    dataset_version: str = Field(min_length=1)
    tagger_revision: str = Field(min_length=1)
    wordlist_revision: str = Field(min_length=1)
    profile_revision: str | None = None
    level_fit: tuple[CoverageSummary, ...] = ()
    pupil_level: tuple[CoverageSummary, ...] = ()
    target_structure: tuple[TargetStructureRow, ...] = ()
    unreadable: int = Field(ge=0)
