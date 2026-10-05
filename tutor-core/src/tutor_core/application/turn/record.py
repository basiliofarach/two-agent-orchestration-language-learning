"""Snapshot the finished graph state into one sealed audit record (REQ-AUDIT)."""

from datetime import datetime

from tutor_core.application.turn.state import TurnGraphState
from tutor_core.domain.audit.record_hash import AuditRecordHash
from tutor_core.domain.models.audit import (
    GATE_ORDER,
    ChainHead,
    GateEvaluation,
    TurnAuditRecord,
)
from tutor_core.domain.models.safety import StoredLearnerPrompt
from tutor_core.domain.models.verdict import GateVerdict


class GateRows:
    """Four rows: each gate that ran, then ``not_evaluated`` for the rest.

    A gate that was not reached cites the rule of the verdict that halted
    the turn, and its reason names that gate and decision. The log therefore
    separates checked-and-passed, checked-and-fired, and not reached
    (REQ-GATES).
    """

    def rows(
        self, verdicts: tuple[GateVerdict, ...], at: datetime
    ) -> tuple[GateEvaluation, ...]:
        """Return one row per gate, in REQ-GATES order."""
        if not verdicts or len(verdicts) > len(GATE_ORDER):
            msg = "a turn records between one and four gate verdicts"
            raise ValueError(msg)
        rows: list[GateEvaluation] = []
        for verdict in verdicts:
            rows.append(
                GateEvaluation.model_validate(
                    {
                        "gate_name": verdict.gate_name,
                        "decision": verdict.decision,
                        "reason": verdict.reason,
                        "policy_rule_id": verdict.policy_rule_id,
                        "evaluated_at": at,
                    }
                )
            )
        halting = verdicts[-1]
        for stage in GATE_ORDER[len(verdicts) :]:
            rows.append(
                GateEvaluation(
                    gate_name=stage,
                    decision="not_evaluated",
                    reason=(
                        f"Not reached: {halting.gate_name} returned {halting.decision}."
                    ),
                    policy_rule_id=halting.policy_rule_id,
                    evaluated_at=at,
                )
            )
        return tuple(rows)


class TurnRecordBuilder:
    """Build the frozen record from the live state, then seal it.

    The record is a snapshot: later assignment to the live ``TurnState``
    does not reach it (DEC-0010). Generation fields are present together
    only when the model ran; a refusal before the model, or a halt before
    generation, stores them as ``None`` (REQ-AUDIT).
    """

    def __init__(self, hasher: AuditRecordHash, gates: GateRows) -> None:
        self._hasher = hasher
        self._gates = gates

    def build(
        self,
        state: TurnGraphState,
        head: ChainHead,
        policy_version: str,
        recorded_at: datetime,
    ) -> TurnAuditRecord:
        """Return the sealed record for ``state`` at ``head``."""
        turn = state.turn
        if turn.learner_prompt is None:
            msg = "a turn is recorded only after its prompt was redacted"
            raise ValueError(msg)
        retrieved = turn.retrieved
        context_ids = (
            ()
            if retrieved is None
            else tuple(str(snippet.chunk_id) for snippet in retrieved.snippets)
        )
        fields: dict[str, object] = {
            "turn_id": turn.turn_id,
            "session_id": turn.session_id,
            "turn_index": head.turn_index,
            "learner_prompt": StoredLearnerPrompt.model_validate(turn.learner_prompt),
            "retrieved_context_ids": context_ids,
            "gate_evaluations": self._gates.rows(state.verdicts, recorded_at),
            "policy_version": policy_version,
            "previous_record_hash": head.previous_record_hash,
            "record_hash": "unsealed",
            "recorded_at": recorded_at,
            **self._generation(state),
        }
        unsealed = TurnAuditRecord.model_validate(fields)
        return unsealed.model_copy(
            update={"record_hash": self._hasher.digest(unsealed)}
        )

    def _generation(self, state: TurnGraphState) -> dict[str, object]:
        draft = state.draft
        if draft is None or not draft.model_ran():
            return {}
        unit = draft.unit
        return {
            "model_revision": draft.model_revision,
            "template_version": draft.template_version,
            "decoding_params": draft.decoding_params,
            "output_before_checks": unit.output_before_checks,
            "output_after_checks": unit.output_after_checks,
            "ai_disclosure": unit.ai_disclosure,
            "refused": unit.refused,
            "safety_flags": draft.safety_flags,
            "source_support": unit.support,
        }
