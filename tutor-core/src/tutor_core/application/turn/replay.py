"""Replay a recorded turn from the log. A mismatch fails closed."""

from pydantic import BaseModel, ConfigDict

from tutor_core.domain.audit.record_hash import AuditRecordHash
from tutor_core.domain.models.audit import TurnAuditRecord
from tutor_core.domain.ports.clock import ClockPort
from tutor_core.domain.ports.language_model import LanguageModelPort


class ReplayRejected(Exception):
    """The clock or the model revision is not the one the record was sealed with.

    Replay does not call the model. It returns the stored output only when
    the injected clock and the injected revision match the row (REQ-AUDIT).
    """


class ReplayOutput(BaseModel):
    """The stored output, reproduced rather than generated again."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    turn_output: str
    checkpoint_id: str


class TurnReplay:
    """Reproduce one recorded output. ``record_hash`` is the checkpoint id.

    The hash is already on the audit record (BE-21). Resolving it means
    finding the row whose ``record_hash`` is that id. A clock that is not
    the recorded instant, or a model revision that is not the recorded SHA,
    fails closed and returns nothing.
    """

    def __init__(
        self,
        model: LanguageModelPort,
        clock: ClockPort,
        hasher: AuditRecordHash,
    ) -> None:
        self._model = model
        self._clock = clock
        self._hasher = hasher

    def output(self, record: TurnAuditRecord) -> ReplayOutput:
        """Return the stored output when the clock and revision match."""
        if record.model_revision is None or record.output_after_checks is None:
            msg = "the recorded turn has no model output to replay"
            raise ReplayRejected(msg)
        if self._model.revision() != record.model_revision:
            msg = "model revision does not match the recorded turn"
            raise ReplayRejected(msg)
        if self._clock.now() != record.recorded_at:
            msg = "clock does not match the recorded instant"
            raise ReplayRejected(msg)
        if record.record_hash != self._hasher.digest(record):
            msg = "record hash does not match the sealed record"
            raise ReplayRejected(msg)
        return ReplayOutput(
            turn_output=record.output_after_checks,
            checkpoint_id=record.record_hash,
        )

    def resolve(
        self, checkpoint_id: str, records: tuple[TurnAuditRecord, ...]
    ) -> TurnAuditRecord:
        """Return the log entry ``checkpoint_id`` names."""
        for record in records:
            if record.record_hash == checkpoint_id:
                return record
        msg = "checkpoint does not resolve to a log entry"
        raise ReplayRejected(msg)
