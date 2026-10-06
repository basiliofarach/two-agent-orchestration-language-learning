"""Read sealed turn records. The statements are selects only."""

from datetime import datetime
from uuid import UUID

from tutor_api.adapters.persistence.base import BaseRepository
from tutor_api.adapters.persistence.sealed import SealedValue
from tutor_core.domain.models.audit import GATE_ORDER, HumanAction, TurnAuditRecord
from tutor_core.domain.ports.audit_query import AuditQueryPort
from tutor_core.domain.ports.cipher import CipherPort
from tutor_core.domain.ports.unit_of_work import TransactionConnection


class AuditRecordDecoder:
    """Rebuild a frozen record from one row and its gate and citation rows.

    The digest covers the record this builds. A column read back in a
    different shape would fail the chain check, so the JSON encoding
    matches the sink that wrote it.
    """

    def __init__(self, sealed: SealedValue) -> None:
        self._sealed = sealed

    def record(
        self,
        row: tuple[object, ...],
        gates: tuple[tuple[object, ...], ...],
        citations: tuple[tuple[object, ...], ...],
    ) -> TurnAuditRecord:
        """Return the record ``row`` was inserted as."""
        fields: dict[str, object] = {
            "turn_id": self._uuid(row[0]),
            "session_id": self._uuid(row[1]),
            "turn_index": int(str(row[2])),
            "learner_prompt": {
                "text": self._sealed.open_text(row[3]),
                "redacted_categories": self._sealed.open_json(row[4]),
            },
            "retrieved_context_ids": tuple(
                str(self._uuid(citation[0])) for citation in citations
            ),
            "model_revision": row[5],
            "template_version": self._sealed.open_optional_text(row[6]),
            "decoding_params": self._sealed.open_optional_json(row[7]),
            "output_before_checks": self._sealed.open_optional_text(row[8]),
            "output_after_checks": self._sealed.open_optional_text(row[9]),
            "ai_disclosure": self._sealed.open_optional_text(row[10]),
            "refused": row[11],
            "safety_flags": self._sealed.open_optional_json(row[12]),
            "source_support": self._sealed.open_optional_json(row[13]),
            "policy_version": str(row[14]),
            "previous_record_hash": str(row[15]),
            "record_hash": str(row[16]),
            "recorded_at": self._instant(row[17]),
            "gate_evaluations": tuple(self._gate(gate) for gate in gates),
        }
        return TurnAuditRecord.model_validate(fields)

    def action(self, row: tuple[object, ...]) -> HumanAction:
        """Return one tutor action. ``edited_output`` stays null except on edit."""
        return HumanAction.model_validate(
            {
                "turn_id": self._uuid(row[0]),
                "tutor_id": self._sealed.open_text(row[1]),
                "action": row[2],
                "edited_output": self._sealed.open_optional_text(row[3]),
                "acted_at": self._instant(row[4]),
            }
        )

    def _gate(self, row: tuple[object, ...]) -> dict[str, object]:
        return {
            "gate_name": row[0],
            "decision": row[1],
            "reason": self._sealed.open_text(row[2]),
            "policy_rule_id": str(row[3]),
            "evaluated_at": self._instant(row[4]),
        }

    def _uuid(self, value: object) -> UUID:
        if isinstance(value, UUID):
            return value
        return UUID(str(value))

    def _instant(self, value: object) -> datetime:
        if isinstance(value, datetime) and value.utcoffset() is not None:
            return value
        msg = "audit instant must be timezone-aware"
        raise ValueError(msg)


class PostgresAuditQuery(BaseRepository, AuditQueryPort):
    """Select the audit tables. There is no insert, update, or delete.

    The application role already holds SELECT. This adapter does not ask
    for more. Learner text comes back redacted, because that is what was
    stored (REQ-MINOR).
    """

    _TURNS = """
        SELECT
            turn_id, session_id, turn_index,
            learner_prompt_redacted, redacted_categories,
            model_revision, template_version, decoding_params,
            output_before_checks, output_after_checks, ai_disclosure,
            refused, safety_flags, source_support,
            policy_version, previous_record_hash, record_hash, recorded_at
        FROM turn_audit
        WHERE session_id = :session_id
        ORDER BY turn_index
        """

    _TURN = """
        SELECT
            turn_id, session_id, turn_index,
            learner_prompt_redacted, redacted_categories,
            model_revision, template_version, decoding_params,
            output_before_checks, output_after_checks, ai_disclosure,
            refused, safety_flags, source_support,
            policy_version, previous_record_hash, record_hash, recorded_at
        FROM turn_audit
        WHERE turn_id = :turn_id
        """

    _GATES = f"""
        SELECT gate_name, decision, reason, policy_rule_id, evaluated_at
        FROM gate_evaluation
        WHERE turn_id = :turn_id
        ORDER BY CASE gate_name
            WHEN '{GATE_ORDER[0]}' THEN 0
            WHEN '{GATE_ORDER[1]}' THEN 1
            WHEN '{GATE_ORDER[2]}' THEN 2
            WHEN '{GATE_ORDER[3]}' THEN 3
        END
        """

    _CITATIONS = """
        SELECT chunk_id
        FROM turn_citation
        WHERE turn_id = :turn_id
        ORDER BY ordinal
        """

    _ACTIONS = """
        SELECT turn_id, tutor_id, action, edited_output, acted_at
        FROM human_action
        WHERE turn_id = :turn_id
        ORDER BY acted_at
        """

    def __init__(self, connection: TransactionConnection, cipher: CipherPort) -> None:
        super().__init__(connection)
        self._decoder = AuditRecordDecoder(SealedValue(cipher))

    async def for_session(self, session_id: UUID) -> tuple[TurnAuditRecord, ...]:
        """Return the session chain, oldest turn first."""
        rows = await self._fetch_all(self._TURNS, {"session_id": session_id})
        records: list[TurnAuditRecord] = []
        for row in rows:
            records.append(await self._complete(row))
        return tuple(records)

    async def turn(self, turn_id: UUID) -> TurnAuditRecord | None:
        """Return one record, or ``None`` when it was never appended."""
        row = await self._fetch_one(self._TURN, {"turn_id": turn_id})
        if row is None:
            return None
        return await self._complete(row)

    async def actions(self, turn_id: UUID) -> tuple[HumanAction, ...]:
        """Return the tutor actions for one turn, earliest first."""
        rows = await self._fetch_all(self._ACTIONS, {"turn_id": turn_id})
        return tuple(self._decoder.action(row) for row in rows)

    async def _complete(self, row: tuple[object, ...]) -> TurnAuditRecord:
        turn_id = row[0]
        parameters = {"turn_id": turn_id}
        gates = await self._fetch_all(self._GATES, parameters)
        citations = await self._fetch_all(self._CITATIONS, parameters)
        return self._decoder.record(row, gates, citations)
