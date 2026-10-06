"""Project sealed records into the excerpts the pack is allowed to store."""

from tutor_api.evidence.body import (
    ActionExcerpt,
    DecodingExcerpt,
    GateExcerpt,
    PackBody,
    TurnExcerpt,
)
from tutor_api.evidence.catalogue import ExhibitResult
from tutor_core.domain.models.audit import (
    GateEvaluation,
    HumanAction,
    TurnAuditRecord,
)
from tutor_core.domain.models.safety import DecodingParams, RedactedText, SafetyFlag
from tutor_core.domain.ports.pii_redaction import PiiRedactionPort


class ExcerptProjector:
    """Copy a read into a ``PackBody``. History snapshots are dropped.

    Every learner-facing string is redacted again here, including text the
    log already redacted, so a later edit or a flag message cannot carry a
    name into the file. Flag messages themselves are not copied.
    """

    def __init__(self, redactor: PiiRedactionPort) -> None:
        self._redactor = redactor

    def project(self, found: ExhibitResult, rubric_lines: tuple[str, ...]) -> PackBody:
        """Return the exhibits. The rubric label cannot be changed."""
        return PackBody(
            documents=found.documents,
            turns=tuple(self._turn(record) for record in found.records),
            actions=tuple(self._action(action) for action in found.actions),
            unreadable_sessions=tuple(
                str(session_id) for session_id in found.unreadable_sessions
            ),
            rubric_lines=rubric_lines,
        )

    def _turn(self, record: TurnAuditRecord) -> TurnExcerpt:
        prompt = self._redactor.redact(record.learner_prompt.text)
        before = self._optional(record.output_before_checks)
        after = self._optional(record.output_after_checks)
        disclosure = self._optional(record.ai_disclosure)
        categories = self._union(
            record.learner_prompt.redacted_categories,
            prompt.redacted_categories,
        )
        return TurnExcerpt(
            turn_id=str(record.turn_id),
            session_id=str(record.session_id),
            turn_index=record.turn_index,
            learner_prompt_redacted=prompt.text,
            redacted_categories=categories,
            retrieved_context_ids=record.retrieved_context_ids,
            context_digest=record.context_digest,
            model_revision=record.model_revision,
            template_version=record.template_version,
            decoding_params=self._decoding(record.decoding_params),
            output_before_checks=None if before is None else before.text,
            output_after_checks=None if after is None else after.text,
            ai_disclosure=None if disclosure is None else disclosure.text,
            refused=record.refused,
            safety_flag_categories=self._categories(record.safety_flags),
            prompt_safety_flag_categories=self._categories(record.prompt_safety_flags),
            unsupported_claims=self._unsupported(record),
            policy_version=record.policy_version,
            previous_record_hash=record.previous_record_hash,
            record_hash=record.record_hash,
            gates=tuple(self._gate(row) for row in record.gate_evaluations),
        )

    def _action(self, action: HumanAction) -> ActionExcerpt:
        edited = self._optional(action.edited_output)
        return ActionExcerpt(
            turn_id=str(action.turn_id),
            tutor_id=action.tutor_id,
            action=action.action,
            edited_output_redacted=None if edited is None else edited.text,
            acted_at=action.acted_at.isoformat(),
            chained=action.chained(),
        )

    def _gate(self, row: GateEvaluation) -> GateExcerpt:
        return GateExcerpt(
            gate_name=row.gate_name,
            decision=row.decision,
            policy_rule_id=row.policy_rule_id,
            evaluated_at=row.evaluated_at.isoformat(),
        )

    def _optional(self, value: str | None) -> RedactedText | None:
        if value is None:
            return None
        return self._redactor.redact(value)

    def _decoding(self, params: DecodingParams | None) -> DecodingExcerpt | None:
        if params is None:
            return None
        return DecodingExcerpt(
            temperature=params.temperature,
            top_p=params.top_p,
            max_tokens=params.max_tokens,
        )

    def _categories(self, flags: tuple[SafetyFlag, ...] | None) -> tuple[str, ...]:
        if flags is None:
            return ()
        return tuple(flag.category for flag in flags)

    def _unsupported(self, record: TurnAuditRecord) -> int:
        support = record.source_support
        if support is None:
            return 0
        return len(support.unsupported)

    def _union(self, kept: tuple[str, ...], found: tuple[str, ...]) -> tuple[str, ...]:
        categories = list(kept)
        for category in found:
            if category not in categories:
                categories.append(category)
        return tuple(categories)
