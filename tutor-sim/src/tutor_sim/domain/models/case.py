"""A case, its expectation, and the utterance once it has been realised."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

OutcomeClass = Literal[
    "released_for_approval",
    "held",
    "refused",
    "stopped_before_retrieval",
]
GateStage = Literal[
    "context_and_permission",
    "conflict_and_ambiguity",
    "sensitivity_and_high_stakes",
    "drift_and_anomaly",
]
LabelBasis = Literal["construction", "requirement", "output_dependent"]
Intent = Literal[
    "I1",
    "I2",
    "I3",
    "I4",
    "I5",
    "I6",
    "I7",
    "I8",
    "I9a",
    "I9b",
    "I10",
    "I11",
    "I12",
    "I13",
]


class Expected(BaseModel):
    """The outcome fixed when the case is built. It is not a model's score."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    accept: tuple[OutcomeClass, ...] = Field(min_length=1)
    gate: GateStage | None = None
    decision: Literal["pause", "stop"] | None = None
    rule_id: str | None = None
    rule_ids: tuple[str, ...] = ()
    model_called: bool | None = None
    must_not_contain: tuple[str, ...] = ()
    basis: LabelBasis


class CaseSpec(BaseModel):
    """One planned case, before a pupil utterance exists."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    split: Literal["dev", "test"]
    persona_id: str = Field(min_length=1)
    intent: Intent
    variant: Literal["canonical", "noisy"]
    base_case_id: str | None = None
    req_eval_case: int | None = Field(default=None, ge=1, le=8)
    topic_id: str | None = None
    payload_id: str | None = None
    requested_history_fields: tuple[str, ...] = ()
    expected: Expected


class Construction(BaseModel):
    """Whether the planted payload survived realisation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    payload_present: bool
    attempts: int = Field(ge=1, le=3)
    discarded: bool


class GeneratorStamp(BaseModel):
    """The role model that wrote the utterance. Tests stub this."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    weights_sha: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed: int
    temperature: float
    template_version: str = Field(min_length=1)
    card_version: str = Field(min_length=1)


class StimulusCase(CaseSpec):
    """A case plus the checked utterance."""

    utterance: str = Field(min_length=1)
    construction: Construction
    generator: GeneratorStamp


class EpisodeSpec(BaseModel):
    """A closed-loop episode. Eight turns is the cap (DEC-0015)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    episode_id: str = Field(min_length=1)
    persona_id: str = Field(min_length=1)
    tutor_role: Literal["T1", "T2", "T3", "T4"]
    max_turns: int = Field(ge=1, le=8)
    script: Literal["open", "S1_drift", "S2_stop"]
    planned_intents: tuple[Intent, ...] = Field(min_length=1)
    stop_at_turn: int | None = None
