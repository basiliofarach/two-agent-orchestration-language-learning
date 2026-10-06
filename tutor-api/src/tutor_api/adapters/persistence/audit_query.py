"""Read sealed turn records. The statements are selects only."""

from uuid import UUID

from pydantic import ValidationError

from tutor_api.adapters.persistence.base import BaseRepository, RowReader
from tutor_api.adapters.persistence.sealed import SealedValue
from tutor_core.domain.models.audit import GATE_ORDER, HumanAction, TurnAuditRecord
from tutor_core.domain.models.retrieval import Snippet, SourceRef
from tutor_core.domain.ports.audit_query import AuditQueryPort, AuditRecordUnreadable
from tutor_core.domain.ports.unit_of_work import TransactionConnection


class AuditRecordDecoder(RowReader):
    """Rebuild a frozen record, action or cited chunk from its rows.

    The digest covers the record this builds. A column read back in a
    different shape would fail the chain check, so the JSON decoding
    matches the sink that wrote it. It runs no statement of its own.
    """

    def __init__(self, sealed: SealedValue) -> None:
        self._sealed = sealed

    def record(
        self,
        row: tuple[object, ...],
        gates: tuple[tuple[object, ...], ...],
        citations: tuple[tuple[object, ...], ...],
    ) -> TurnAuditRecord:
        """Return the record ``row`` was inserted as.

        A row set that no longer validates — an extra gate row is the case
        the review found — raises ``AuditRecordUnreadable`` on the turn.
        """
        turn_id = self._uuid(row[0])
        fields: dict[str, object] = {
            "turn_id": turn_id,
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
            "history_snapshot": self._sealed.open_optional_json(row[18]),
            "prompt_safety_flags": self._sealed.open_optional_json(row[19]),
            "context_digest": row[20],
            "gate_evaluations": tuple(self._gate(gate) for gate in gates),
        }
        try:
            return TurnAuditRecord.model_validate(fields)
        except ValidationError as exc:
            raise AuditRecordUnreadable(turn_id) from exc

    def action(self, row: tuple[object, ...]) -> HumanAction:
        """Return one tutor action. Chain fields are null on legacy rows."""
        index = row[6]
        return HumanAction.model_validate(
            {
                "turn_id": self._uuid(row[0]),
                "tutor_id": self._sealed.open_text(row[1]),
                "action": row[2],
                "edited_output": self._sealed.open_optional_text(row[3]),
                "acted_at": self._instant(row[4]),
                "session_id": None if row[5] is None else self._uuid(row[5]),
                "action_index": None if index is None else int(str(index)),
                "previous_action_hash": row[7],
                "action_hash": row[8],
            }
        )

    def snippet(self, row: tuple[object, ...]) -> Snippet:
        """Return one cited chunk with its curated source."""
        return Snippet(
            chunk_id=self._uuid(row[0]),
            ordinal=int(str(row[1])),
            content=self._sealed.open_text(row[2]),
            source=SourceRef(
                document_id=self._uuid(row[3]),
                source_uri=str(row[4]),
                version=str(row[5]),
                review_status=str(row[6]),
            ),
        )

    def _gate(self, row: tuple[object, ...]) -> dict[str, object]:
        return {
            "gate_name": row[0],
            "decision": row[1],
            "reason": self._sealed.open_text(row[2]),
            "policy_rule_id": str(row[3]),
            "evaluated_at": self._instant(row[4]),
        }


class PostgresAuditQuery(BaseRepository, AuditQueryPort):
    """Select the audit tables. There is no insert, update, or delete.

    The application role already holds SELECT on the audit tables and on
    ``kb_chunk`` and ``kb_document``. This adapter does not ask for more.
    Learner text comes back redacted, because that is what was stored
    (REQ-MINOR).
    """

    _RECORD_COLUMNS = """
            turn_id, session_id, turn_index,
            learner_prompt_redacted, redacted_categories,
            model_revision, template_version, decoding_params,
            output_before_checks, output_after_checks, ai_disclosure,
            refused, safety_flags, source_support,
            policy_version, previous_record_hash, record_hash, recorded_at,
            history_snapshot, prompt_safety_flags, context_digest
        """

    _TURNS = f"""
        SELECT {_RECORD_COLUMNS}
        FROM turn_audit
        WHERE session_id = :session_id
        ORDER BY turn_index
        """

    _TURN = f"""
        SELECT {_RECORD_COLUMNS}
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
        END, evaluated_at, id
        """

    _CITATION_IDS = """
        SELECT chunk_id
        FROM turn_citation
        WHERE turn_id = :turn_id
        ORDER BY ordinal
        """

    _ACTION_COLUMNS = """
            turn_id, tutor_id, action, edited_output, acted_at,
            session_id, action_index, previous_action_hash, action_hash
        """

    _ACTIONS = f"""
        SELECT {_ACTION_COLUMNS}
        FROM human_action
        WHERE turn_id = :turn_id
        ORDER BY acted_at, action_index NULLS FIRST, id
        """

    # Legacy rows have no session_id; they are reached through their turn.
    _SESSION_ACTIONS = f"""
        SELECT {_ACTION_COLUMNS}
        FROM human_action AS action
        WHERE action.session_id = :session_id
           OR (
               action.session_id IS NULL
               AND action.turn_id IN (
                   SELECT turn_id FROM turn_audit WHERE session_id = :session_id
               )
           )
        ORDER BY action.action_index NULLS FIRST, action.acted_at, action.id
        """

    _CITED_CHUNKS = """
        SELECT chunk.id, chunk.ordinal, chunk.content,
               document.id, document.source_uri, document.version,
               document.review_status
        FROM turn_citation AS citation
        JOIN kb_chunk AS chunk ON chunk.id = citation.chunk_id
        JOIN kb_document AS document ON document.id = chunk.document_id
        WHERE citation.turn_id = :turn_id
        ORDER BY citation.ordinal
        """

    def __init__(
        self, connection: TransactionConnection, decoder: AuditRecordDecoder
    ) -> None:
        super().__init__(connection)
        self._decoder = decoder

    async def for_session(self, session_id: UUID) -> tuple[TurnAuditRecord, ...]:
        """Return the session chain, oldest turn first."""
        rows = await self._fetch_all(self._TURNS, {"session_id": session_id})
        return tuple([await self._complete(row) for row in rows])

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

    async def session_actions(self, session_id: UUID) -> tuple[HumanAction, ...]:
        """Return every action in the session; legacy rows first, then the chain."""
        rows = await self._fetch_all(self._SESSION_ACTIONS, {"session_id": session_id})
        return tuple(self._decoder.action(row) for row in rows)

    async def citations(self, turn_id: UUID) -> tuple[Snippet, ...]:
        """Return the cited chunks with their curated sources."""
        rows = await self._fetch_all(self._CITED_CHUNKS, {"turn_id": turn_id})
        return tuple(self._decoder.snippet(row) for row in rows)

    async def _complete(self, row: tuple[object, ...]) -> TurnAuditRecord:
        parameters = {"turn_id": row[0]}
        gates = await self._fetch_all(self._GATES, parameters)
        citations = await self._fetch_all(self._CITATION_IDS, parameters)
        return self._decoder.record(row, gates, citations)
