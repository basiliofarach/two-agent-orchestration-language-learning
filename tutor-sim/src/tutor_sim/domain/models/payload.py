"""A planted string. The label rests on these bytes, not on the role model."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PayloadCategory = Literal[
    "direct_injection",
    "indirect_injection",
    "child_safety",
    "pii",
    "open_web",
    "history_probe",
    "proficiency",
]
PayloadSplit = Literal["dev", "test"]
PayloadLanguage = Literal["en", "es"]
PiiKind = Literal["name", "email", "phone", "address"]


class PiiMarks:
    """The PII marks on a payload, and the value the leak check looks for.

    ``text`` is the carrier the persona plants ("my name is Ada Lovelace.
    ref 4"). ``pii_value`` is the personal datum inside it ("Ada Lovelace").
    The I10 leak check searches for the value, so a partial leak that drops
    the carrier words is still a leak.
    """

    def check(
        self,
        category: PayloadCategory,
        text: str,
        language: PayloadLanguage,
        pii_kind: PiiKind | None,
        pii_value: str | None,
    ) -> None:
        """Refuse a PII payload without its marks, or marks on anything else."""
        if category == "pii":
            if pii_kind is None:
                msg = "a PII payload names its kind"
                raise ValueError(msg)
            if pii_value is None:
                msg = "a PII payload names its value"
                raise ValueError(msg)
            if pii_value not in text:
                msg = "the PII value must be planted in the payload text"
                raise ValueError(msg)
            return
        if pii_kind is not None or pii_value is not None or language == "es":
            msg = "only a PII payload is Spanish, names a kind, or names a value"
            raise ValueError(msg)


class PayloadDraft(BaseModel):
    """A payload before the seeded split is assigned."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    category: PayloadCategory
    text: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    licence: str = Field(min_length=1)
    redistributable: bool
    language: PayloadLanguage = "en"
    pii_kind: PiiKind | None = None
    pii_value: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def pii_is_marked(self) -> "PayloadDraft":
        """Spanish forms, a PII kind and a PII value belong to PII only."""
        PiiMarks().check(
            self.category, self.text, self.language, self.pii_kind, self.pii_value
        )
        return self


class Payload(BaseModel):
    """One string planted verbatim in a stimulus."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    payload_id: str = Field(min_length=1)
    category: PayloadCategory
    text: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    licence: str = Field(min_length=1)
    redistributable: bool
    split: PayloadSplit
    language: PayloadLanguage
    pii_kind: PiiKind | None = None
    pii_value: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def pii_is_marked(self) -> "Payload":
        """Spanish forms, a PII kind and a PII value belong to PII only."""
        PiiMarks().check(
            self.category, self.text, self.language, self.pii_kind, self.pii_value
        )
        return self
