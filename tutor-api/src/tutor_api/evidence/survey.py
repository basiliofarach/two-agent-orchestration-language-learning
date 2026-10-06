"""Verify every session's chains for the evidence pack (REQ-AUDIT)."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from tutor_core.domain.audit.chain import ChainVerifier
from tutor_core.domain.ports.audit_query import AuditQueryPort, AuditRecordUnreadable
from tutor_core.domain.ports.unit_of_work import (
    TransactionalWork,
    TransactionConnection,
)


class ChainSurveyResult(BaseModel):
    """What the survey found. Counts and ids only; no learner text."""

    model_config = ConfigDict(extra="forbid")

    policy_version: str | None = None
    sessions: int = Field(default=0, ge=0)
    turns: int = Field(default=0, ge=0)
    actions: int = Field(default=0, ge=0)
    unchained_actions: int = Field(default=0, ge=0)
    broken_sessions: tuple[UUID, ...] = ()

    def chain_status(self) -> Literal["intact", "broken"]:
        """``intact`` when every session's turn and action chains link."""
        return "broken" if self.broken_sessions else "intact"


class ChainSurvey(TransactionalWork):
    """Walk every session on the owner's connection. Selects only.

    Each session's turn chain and action chain are verified the way the
    audit route verifies them, so the pack reports the log as it is rather
    than a value the command was handed.
    """

    _SESSIONS = "SELECT id FROM tutoring_session ORDER BY started_at, id"

    _POLICY = """
        SELECT version FROM policy_version
        ORDER BY effective_from DESC
        LIMIT 1
        """

    def __init__(
        self,
        query: AuditQueryPort,
        verifier: ChainVerifier,
        result: ChainSurveyResult,
    ) -> None:
        self._query = query
        self._verifier = verifier
        self._result = result

    async def run(self, connection: TransactionConnection) -> None:
        """Fill the result."""
        policy = await connection.fetch_one(self._POLICY, {})
        self._result.policy_version = None if policy is None else str(policy[0])
        broken: list[UUID] = []
        rows = await connection.fetch_all(self._SESSIONS, {})
        for row in rows:
            session_id = row[0] if isinstance(row[0], UUID) else UUID(str(row[0]))
            if not await self._intact(session_id):
                broken.append(session_id)
        self._result.sessions = len(rows)
        self._result.broken_sessions = tuple(broken)

    async def _intact(self, session_id: UUID) -> bool:
        actions = await self._query.session_actions(session_id)
        self._result.actions += len(actions)
        self._result.unchained_actions += sum(
            1 for action in actions if not action.chained()
        )
        try:
            records = await self._query.for_session(session_id)
        except AuditRecordUnreadable:
            return False
        self._result.turns += len(records)
        return (
            self._verifier.find_break(records) is None
            and self._verifier.find_action_break(actions) is None
        )
