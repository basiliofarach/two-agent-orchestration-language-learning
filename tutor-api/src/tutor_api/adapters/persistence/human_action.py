"""Append a tutor action, and stop the session when the action is stop."""

from uuid import UUID, uuid4

from tutor_api.adapters.persistence.base import BaseRepository
from tutor_api.adapters.persistence.sealed import SealedValue
from tutor_core.domain.models.audit import HumanAction
from tutor_core.domain.ports.cipher import CipherPort
from tutor_core.domain.ports.human_action import ActionRejected, HumanActionPort
from tutor_core.domain.ports.unit_of_work import TransactionConnection


class StoppedSessionMark:
    """Recognise the database refusing to stop a session that cannot be stopped.

    ``mark_session_stopped`` raises SQLSTATE ``SS001``. The driver error
    carries ``sqlstate``; SQLAlchemy wraps it as ``orig``.
    """

    SQLSTATE = "SS001"

    def raised_by(self, error: BaseException) -> bool:
        """Whether ``error``, or the driver error inside it, is that refusal."""
        for candidate in (error, getattr(error, "orig", None), error.__cause__):
            if getattr(candidate, "sqlstate", None) == self.SQLSTATE:
                return True
        return False


class PostgresHumanAction(BaseRepository, HumanActionPort):
    """Insert ``human_action``. A stop also calls ``mark_session_stopped``.

    The application role has INSERT on ``human_action`` and no UPDATE on
    ``tutoring_session``. The stop runs as the migration owner inside the
    security-definer function, so the role never receives that UPDATE
    (ARCHITECTURE §8.3). Both statements share the enlisted transaction.
    """

    _INSERT = """
        INSERT INTO human_action (
            id, turn_id, tutor_id, action, edited_output, acted_at
        ) VALUES (
            :id, :turn_id, :tutor_id, :action, :edited_output, :acted_at
        )
        """

    _STOP = """
        SELECT mark_session_stopped(
            CAST(:session_id AS uuid), :stopped, :reason
        )
        """

    def __init__(self, connection: TransactionConnection, cipher: CipherPort) -> None:
        super().__init__(connection)
        self._sealed = SealedValue(cipher)
        self._stopped = StoppedSessionMark()

    async def append(self, action: HumanAction, session_id: UUID) -> None:
        """Insert the action. A stop marks the session in the same transaction."""
        await self._execute(
            self._INSERT,
            {
                "id": uuid4(),
                "turn_id": action.turn_id,
                "tutor_id": self._sealed.seal_text(action.tutor_id),
                "action": action.action,
                "edited_output": (
                    None
                    if action.edited_output is None
                    else self._sealed.seal_text(action.edited_output)
                ),
                "acted_at": action.acted_at,
            },
        )
        if action.action != "stop":
            return
        try:
            await self._fetch_one(
                self._STOP,
                {
                    "session_id": session_id,
                    "stopped": action.acted_at,
                    "reason": self._sealed.seal_text("tutor stop"),
                },
            )
        except Exception as exc:
            if self._stopped.raised_by(exc):
                msg = "session is stopped"
                raise ActionRejected(msg) from exc
            raise
