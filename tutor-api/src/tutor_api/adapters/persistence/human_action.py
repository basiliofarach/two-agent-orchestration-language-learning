"""Append a chained tutor action, and stop the session when the action is stop."""

from uuid import UUID, uuid4

from tutor_api.adapters.persistence.base import BaseRepository
from tutor_api.adapters.persistence.schema import HumanActionChain, MarkSessionStopped
from tutor_api.adapters.persistence.sealed import SealedValue
from tutor_core.domain.audit.record_hash import ActionRecordHash
from tutor_core.domain.models.audit import ActionChainHead, HumanAction
from tutor_core.domain.ports.human_action import ActionRejected, HumanActionPort
from tutor_core.domain.ports.unit_of_work import TransactionConnection


class PostgresHumanAction(BaseRepository, HumanActionPort):
    """Insert ``human_action``. A stop also calls ``mark_session_stopped``.

    The application role has INSERT on ``human_action`` and no UPDATE on
    ``tutoring_session``. The stop runs as the migration owner inside the
    security-definer function, which refuses unless this transaction has
    already inserted the stop row (ARCHITECTURE §8.3). Both statements share
    the enlisted transaction.

    Appends for one session take a transaction advisory lock before the
    predecessor read, as the turn sink does. A second action waits, then
    links to the row the first wrote; ``human_action_session_index`` is the
    uniqueness backstop. The database refuses an action on a stopped
    session, a second decision on one turn, and an approval of a turn the
    model never ran on (``HumanActionChain``). Every refusal is
    ``ActionRejected``, and the insert rolls back.
    """

    _INSERT = """
        INSERT INTO human_action (
            id, turn_id, tutor_id, action, edited_output, acted_at,
            session_id, action_index, previous_action_hash, action_hash
        ) VALUES (
            :id, :turn_id, :tutor_id, :action, :edited_output, :acted_at,
            :session_id, :action_index, :previous_action_hash, :action_hash
        )
        """

    _STOP = """
        SELECT mark_session_stopped(
            CAST(:session_id AS uuid), :stopped, :reason
        )
        """

    # First key of pg_advisory_xact_lock. The audit sink uses 4812 for turns.
    _CHAIN_LOCK_NAMESPACE = 4813

    _LOCK_SESSION = """
        SELECT pg_advisory_xact_lock(
            :namespace, hashtext(CAST(:session_id AS text))
        )
        """

    _PREDECESSOR = """
        SELECT action_hash, action_index
        FROM human_action
        WHERE session_id = :session_id
        ORDER BY action_index DESC
        LIMIT 1
        """

    # A second decision on one turn violates this index (23505).
    _UNIQUE_VIOLATION = "23505"

    def __init__(
        self,
        connection: TransactionConnection,
        sealed: SealedValue,
        hasher: ActionRecordHash,
    ) -> None:
        super().__init__(connection)
        self._sealed = sealed
        self._hasher = hasher

    async def head(self, session_id: UUID) -> ActionChainHead:
        """Where the next action of ``session_id`` attaches. Read only."""
        row = await self._fetch_one(self._PREDECESSOR, {"session_id": session_id})
        if row is None:
            return ActionChainHead(
                previous_action_hash=ActionRecordHash.GENESIS, action_index=0
            )
        return ActionChainHead(
            previous_action_hash=str(row[0]),
            action_index=int(str(row[1])) + 1,
        )

    async def append(self, action: HumanAction) -> None:
        """Insert the action. A stop marks the session in the same transaction."""
        session_id = self._require_chained(action)
        await self._fetch_one(
            self._LOCK_SESSION,
            {"namespace": self._CHAIN_LOCK_NAMESPACE, "session_id": str(session_id)},
        )
        await self._require_predecessor(action, session_id)
        try:
            await self._execute(self._INSERT, self._parameters(action))
            if action.action == "stop":
                await self._fetch_one(
                    self._STOP,
                    {
                        "session_id": str(session_id),
                        "stopped": action.acted_at,
                        "reason": self._sealed.seal_text("tutor stop"),
                    },
                )
        except Exception as exc:
            refusal = self._refusal(exc)
            if refusal is None:
                raise
            raise ActionRejected(refusal) from exc

    def _require_chained(self, action: HumanAction) -> UUID:
        if not action.chained() or action.session_id is None:
            msg = "an action is appended with its chain position"
            raise ActionRejected(msg)
        if action.action_hash != self._hasher.digest(action):
            msg = "action hash does not match the canonical digest"
            raise ActionRejected(msg)
        return action.session_id

    async def _require_predecessor(self, action: HumanAction, session_id: UUID) -> None:
        head = await self.head(session_id)
        if (
            action.previous_action_hash != head.previous_action_hash
            or action.action_index != head.action_index
        ):
            msg = "another action was recorded first; reload and try again"
            raise ActionRejected(msg)

    def _refusal(self, exc: BaseException) -> str | None:
        if self._raised_sqlstate(exc, HumanActionChain.SQLSTATE):
            return self._message(exc, "the session or turn cannot take this action")
        if self._raised_sqlstate(exc, MarkSessionStopped.SQLSTATE):
            return "session is stopped"
        if self._raised_sqlstate(exc, self._UNIQUE_VIOLATION):
            return "this turn already has a tutor decision"
        return None

    def _message(self, exc: BaseException, fallback: str) -> str:
        # The guard's RAISE text names the refusal and carries no learner data.
        for candidate in (exc, getattr(exc, "orig", None), exc.__cause__):
            diag = getattr(candidate, "diag", None)
            primary = getattr(diag, "message_primary", None)
            if isinstance(primary, str) and primary:
                return primary
        return fallback

    def _parameters(self, action: HumanAction) -> dict[str, object]:
        return {
            "id": uuid4(),
            "turn_id": action.turn_id,
            "tutor_id": self._sealed.seal_text(action.tutor_id),
            "action": action.action,
            "edited_output": self._sealed.seal_optional_text(action.edited_output),
            "acted_at": action.acted_at,
            "session_id": action.session_id,
            "action_index": action.action_index,
            "previous_action_hash": action.previous_action_hash,
            "action_hash": action.action_hash,
        }
