"""Walk a session's records and name the one that breaks the chain."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from tutor_core.domain.audit.record_hash import ActionRecordHash, AuditRecordHash
from tutor_core.domain.models.audit import HumanAction, TurnAuditRecord


class ChainBreak(BaseModel):
    """The record that no longer continues the chain (REQ-AUDIT).

    ``excised`` means this record's ``previous_record_hash`` is not the
    predecessor's ``record_hash`` (or the genesis value, for the first
    record). The missing record is gone, so the report names the record
    that no longer links. ``tampered`` means the link holds and the stored
    ``record_hash`` is not the digest of this record.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    turn_id: UUID
    reason: Literal["tampered", "excised"]


class ActionChainBreak(BaseModel):
    """The tutor action that no longer continues its session's action chain.

    ``excised`` and ``tampered`` mean what they mean for a turn record.
    ``action_index`` names the position, because an action has no id of
    its own in the domain.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    action_index: int
    turn_id: UUID
    reason: Literal["tampered", "excised"]


class ChainVerifier:
    """Check a session's records, and its tutor actions, in append order."""

    def __init__(self, hasher: AuditRecordHash, actions: ActionRecordHash) -> None:
        self._hasher = hasher
        self._actions = actions

    def find_break(self, records: tuple[TurnAuditRecord, ...]) -> ChainBreak | None:
        """Return the first break, or ``None`` when the chain holds."""
        previous = AuditRecordHash.GENESIS
        for record in records:
            if record.previous_record_hash != previous:
                return ChainBreak(turn_id=record.turn_id, reason="excised")
            if record.record_hash != self._hasher.digest(record):
                return ChainBreak(turn_id=record.turn_id, reason="tampered")
            previous = record.record_hash
        return None

    def find_action_break(
        self, actions: tuple[HumanAction, ...]
    ) -> ActionChainBreak | None:
        """Return the first break in the chained actions, or ``None``.

        Actions written before the chain existed are skipped; the caller
        reports how many there were. The chained ones are walked in
        ``action_index`` order from the genesis value.
        """
        chained = sorted(
            (action for action in actions if action.chained()),
            key=lambda action: action.action_index or 0,
        )
        previous = ActionRecordHash.GENESIS
        for expected, action in enumerate(chained):
            if (
                action.previous_action_hash != previous
                or action.action_index != expected
            ):
                return ActionChainBreak(
                    action_index=expected, turn_id=action.turn_id, reason="excised"
                )
            if action.action_hash != self._actions.digest(action):
                return ActionChainBreak(
                    action_index=expected, turn_id=action.turn_id, reason="tampered"
                )
            previous = action.action_hash
        return None
