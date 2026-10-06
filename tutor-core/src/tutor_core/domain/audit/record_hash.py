"""Canonical digest of one turn record (REQ-AUDIT)."""

import hashlib
import json
from typing import Self

from pydantic import BaseModel, ConfigDict

from tutor_core.domain.models.audit import HumanAction, TurnAuditRecord
from tutor_core.domain.models.safety import StoredLearnerPrompt


class HistoricalPrompt(BaseModel):
    """The prompt fields a digest covered before the prompt was nested.

    ``learner_prompt`` stores the text and the categories together. The
    hash still names them as the two top-level fields the earlier rows
    were sealed with.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    learner_prompt_redacted: str
    redacted_categories: tuple[str, ...]

    @classmethod
    def from_stored(cls, prompt: StoredLearnerPrompt) -> Self:
        """Project the nested prompt back onto those two fields."""
        return cls(
            learner_prompt_redacted=prompt.text,
            redacted_categories=prompt.redacted_categories,
        )


class AuditRecordHash:
    """SHA-256 of the canonical turn record.

    ``GENESIS`` is the predecessor of the first record in a session. It is
    64 hex zeros: the same width as a digest, and not the hash of a record.
    A later record's ``previous_record_hash`` is its predecessor's
    ``record_hash``.

    The digest excludes ``record_hash`` itself and includes every other
    field. Generation fields that are absent stay in the payload as null.
    A later human action is not on this record, so it is not part of the
    turn hash.
    """

    GENESIS = "0" * 64

    def digest(self, record: TurnAuditRecord) -> str:
        """Return the hex digest of ``canonical(record)``."""
        payload = self.canonical(record).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def canonical(self, record: TurnAuditRecord) -> str:
        """Return the JSON whose digest is ``record_hash``.

        Keys are sorted and separators carry no whitespace, so two equal
        records produce one string. Absent generation fields are null, not
        omitted.

        ``gate_evaluations`` is covered when present, so a gate row cannot be
        edited without breaking the chain. An empty tuple is omitted, which
        keeps the digest of a record sealed before gate rows existed.
        ``history_snapshot``, ``prompt_safety_flags`` and ``context_digest``
        are covered when present and omitted when ``None``, for the same
        reason.

        The prompt is written as the two fields the historical digest
        covered, ``learner_prompt_redacted`` and ``redacted_categories``.
        The domain model nests them on ``learner_prompt``; hashing that
        object would report every row sealed before the nesting as tampered.
        """
        payload = record.model_dump(
            mode="json", exclude={"record_hash", "learner_prompt"}
        )
        if not record.gate_evaluations:
            # Rows sealed before gate rows were recorded hashed no such key.
            del payload["gate_evaluations"]
        if record.history_snapshot is None:
            # Rows sealed before the snapshot was recorded hashed no such key.
            del payload["history_snapshot"]
        if record.prompt_safety_flags is None:
            # Rows sealed before prompt flags were recorded hashed no such key.
            del payload["prompt_safety_flags"]
        if record.context_digest is None:
            # Rows sealed before the context digest hashed no such key.
            del payload["context_digest"]
        prompt = HistoricalPrompt.from_stored(record.learner_prompt)
        payload.update(prompt.model_dump(mode="json"))
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )


class ActionRecordHash:
    """SHA-256 of one canonical tutor action (REQ-AUDIT).

    The action chain is built like the turn chain: ``GENESIS`` before the
    first action of a session, and each later ``previous_action_hash`` is
    its predecessor's ``action_hash``. Every field except ``action_hash``
    itself is covered, ``tutor_id`` and ``edited_output`` included, so an
    approval cannot be re-attributed or its released text changed without
    breaking the chain.
    """

    GENESIS = "0" * 64

    def digest(self, action: HumanAction) -> str:
        """Return the hex digest of ``canonical(action)``."""
        return hashlib.sha256(self.canonical(action).encode("utf-8")).hexdigest()

    def canonical(self, action: HumanAction) -> str:
        """Sorted keys, no whitespace, nulls kept: one string per action."""
        payload = action.model_dump(mode="json", exclude={"action_hash"})
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
