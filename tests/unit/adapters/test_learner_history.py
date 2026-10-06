"""History reads select only the requested fields, inside the allowlist."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError
from tests.contract.test_port_contracts import LearnerHistoryPortContract
from tests.support.reversible_cipher import ReversibleCipher
from tests.support.samples import Samples
from tests.support.scripted_connection import ScriptedConnection

from tutor_api.adapters.frozen_clock import FrozenClock
from tutor_api.adapters.persistence.learner_history import (
    HistoryOutcomeCodec,
    PostgresLearnerHistory,
)
from tutor_core.domain.models.learner import HistoryFieldSet, LearnerHistorySnapshot
from tutor_core.domain.ports.learner_history import LearnerHistoryPort

_WHEN = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
_LATER = datetime(2026, 12, 1, tzinfo=UTC)
_EARLIER = datetime(2026, 1, 1, tzinfo=UTC)
_OCCURRED = datetime(2026, 6, 1, tzinfo=UTC)
_BOTH = ("proficiency_level", "events")


class Fields:
    """A ``HistoryFieldSet`` from names, so a test reads as its fields."""

    def of(self, *names: str) -> HistoryFieldSet:
        return HistoryFieldSet.model_validate({"fields": names})


class SequencedConnection(ScriptedConnection):
    """One scripted batch per fetch, in call order."""

    def __init__(self, steps: tuple[tuple[tuple[object, ...], ...], ...]) -> None:
        super().__init__()
        self._steps = list(steps)

    async def fetch_one(
        self, statement: str, parameters: dict[str, object]
    ) -> tuple[object, ...] | None:
        self._record(statement, parameters)
        batch = self._steps.pop(0)
        if not batch:
            return None
        return batch

    async def fetch_all(
        self, statement: str, parameters: dict[str, object]
    ) -> tuple[tuple[object, ...], ...]:
        self._record(statement, parameters)
        return self._steps.pop(0)


class Wired:
    """The history adapter with a scripted connection and a fixed clock."""

    def __init__(
        self,
        fields: tuple[str, ...],
        steps: tuple[tuple[tuple[object, ...], ...], ...] = (),
        allowlist: tuple[str, ...] = _BOTH,
    ) -> None:
        self.connection = SequencedConnection(steps)
        self.requested = Fields().of(*fields)
        self.port = PostgresLearnerHistory(
            self.connection,
            ReversibleCipher(),
            FrozenClock(_WHEN),
            Fields().of(*allowlist),
            HistoryOutcomeCodec(),
        )

    async def read(self) -> LearnerHistorySnapshot:
        return await self.port.read(Samples().learner_id(), self.requested)

    def seal(self, text: str) -> bytes:
        return ReversibleCipher().encrypt(text.encode("utf-8"))

    def outcome(self, correct: bool) -> bytes:
        return ReversibleCipher().encrypt(HistoryOutcomeCodec().encode(correct))


class TestPostgresLearnerHistoryContract(LearnerHistoryPortContract):
    def port(self) -> LearnerHistoryPort:
        return Wired(
            ("proficiency_level",),
            ((_LATER,), (Wired(("proficiency_level",)).seal("A1"),)),
        ).port


class TestHistoryOutcomeCodec:
    def test_both_outcomes_encode_to_one_byte(self) -> None:
        codec = HistoryOutcomeCodec()
        assert len(codec.encode(True)) == len(codec.encode(False)) == 1

    def test_sealed_outcomes_have_the_same_length(self) -> None:
        wired = Wired(())
        assert len(wired.outcome(True)) == len(wired.outcome(False))

    def test_decode_reverses_encode(self) -> None:
        codec = HistoryOutcomeCodec()
        assert codec.decode(codec.encode(True)) is True
        assert codec.decode(codec.encode(False)) is False

    def test_a_word_outcome_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="not one outcome byte"):
            HistoryOutcomeCodec().decode(b"true")


class TestPostgresLearnerHistory:
    async def test_a_request_outside_the_allowlist_raises_before_any_read(
        self,
    ) -> None:
        wired = Wired(("events",), allowlist=("proficiency_level",))
        with pytest.raises(ValueError, match="outside the allowlist: events"):
            await wired.read()
        assert wired.connection.statements == []

    async def test_an_allowlisted_field_not_requested_is_not_read(self) -> None:
        wired = Wired(
            ("proficiency_level",),
            ((_LATER,), (Wired(()).seal("A2"),)),
            allowlist=_BOTH,
        )
        snapshot = await wired.read()
        assert snapshot.events is None
        assert "learner_history_event" not in " ".join(wired.connection.statements)

    async def test_sql_selects_only_requested_columns(self) -> None:
        wired = Wired(
            ("proficiency_level",),
            ((_LATER,), (Wired(("proficiency_level",)).seal("A2"),)),
        )
        snapshot = await wired.read()
        assert snapshot.proficiency_level == "A2"
        assert snapshot.events is None
        joined = " ".join(wired.connection.statements)
        assert "proficiency_level" in joined
        assert "learner_history_event" not in joined
        assert "pseudonym" not in joined
        assert "INSERT" not in joined.upper()
        assert "UPDATE" not in joined.upper()
        assert "DELETE" not in joined.upper()

    async def test_events_are_selected_only_when_admitted(self) -> None:
        wired = Wired(
            ("events",),
            (
                (_LATER,),
                (
                    (
                        Wired(("events",)).seal("greet-1"),
                        Wired(("events",)).outcome(True),
                        _OCCURRED,
                    ),
                ),
            ),
        )
        snapshot = await wired.read()
        assert snapshot.proficiency_level is None
        assert snapshot.events is not None
        assert snapshot.events[0].item_id == "greet-1"
        assert snapshot.events[0].correct is True
        joined = " ".join(wired.connection.statements)
        assert "learner_history_event" in joined
        assert "ORDER BY occurred_at, id" in joined
        assert "proficiency_level" not in joined

    async def test_an_empty_request_yields_an_empty_snapshot(self) -> None:
        wired = Wired((), ((_LATER,),))
        snapshot = await wired.read()
        assert snapshot == LearnerHistorySnapshot(
            learner_id=Samples().learner_id(),
            proficiency_level=None,
            events=None,
        )
        assert len(wired.connection.statements) == 1
        assert "retain_until" in wired.connection.statements[0]

    async def test_expired_retain_until_yields_no_history(self) -> None:
        wired = Wired(("proficiency_level", "events"), ((_EARLIER,),))
        snapshot = await wired.read()
        assert snapshot.proficiency_level is None
        assert snapshot.events is None
        assert len(wired.connection.statements) == 1

    async def test_an_unknown_learner_raises(self) -> None:
        wired = Wired(("proficiency_level",), ((),))
        with pytest.raises(ValueError, match="not known"):
            await wired.read()

    async def test_a_missing_row_on_the_proficiency_read_raises(self) -> None:
        wired = Wired(("proficiency_level",), ((_LATER,), ()))
        with pytest.raises(ValueError, match="not known"):
            await wired.read()

    async def test_a_false_outcome_is_false(self) -> None:
        wired = Wired(
            ("events",),
            (
                (_LATER,),
                (
                    (
                        Wired(("events",)).seal("item"),
                        Wired(("events",)).outcome(False),
                        _OCCURRED,
                    ),
                ),
            ),
        )
        snapshot = await wired.read()
        assert snapshot.events is not None
        assert snapshot.events[0].correct is False

    async def test_an_outcome_that_is_not_an_outcome_byte_raises(self) -> None:
        wired = Wired(
            ("events",),
            (
                (_LATER,),
                (
                    (
                        Wired(("events",)).seal("item"),
                        Wired(("events",)).seal("maybe"),
                        _OCCURRED,
                    ),
                ),
            ),
        )
        with pytest.raises(ValueError, match="not one outcome byte"):
            await wired.read()

    async def test_a_memoryview_ciphertext_is_opened(self) -> None:
        sealed = memoryview(Wired(("proficiency_level",)).seal("B1"))
        wired = Wired(("proficiency_level",), ((_LATER,), (sealed,)))
        snapshot = await wired.read()
        assert snapshot.proficiency_level == "B1"

    async def test_a_bytearray_ciphertext_is_opened(self) -> None:
        sealed = bytearray(Wired(("events",)).outcome(True))
        wired = Wired(
            ("events",),
            ((_LATER,), ((Wired(("events",)).seal("item"), sealed, _OCCURRED),)),
        )
        snapshot = await wired.read()
        assert snapshot.events is not None
        assert snapshot.events[0].correct is True

    async def test_a_value_that_is_not_ciphertext_raises(self) -> None:
        wired = Wired(("proficiency_level",), ((_LATER,), ("not-bytes",)))
        with pytest.raises(ValueError, match="not ciphertext"):
            await wired.read()

    async def test_a_naive_timestamp_raises(self) -> None:
        wired = Wired(("proficiency_level",), ((datetime(2026, 12, 1),),))
        with pytest.raises(ValueError, match="timezone-aware"):
            await wired.read()

    async def test_a_missing_timestamp_raises(self) -> None:
        wired = Wired(("proficiency_level",), (("not-a-time",),))
        with pytest.raises(ValueError, match="timestamp is missing"):
            await wired.read()

    def test_the_adapter_exposes_no_write_method(self) -> None:
        names = {
            name for name in dir(PostgresLearnerHistory) if not name.startswith("_")
        }
        assert names == {"read"}


class TestLearnerHistorySnapshot:
    def test_a_blank_proficiency_is_rejected_and_absence_is_not(self) -> None:
        with pytest.raises(ValidationError, match="proficiency_level is empty"):
            LearnerHistorySnapshot(
                learner_id=Samples().learner_id(),
                proficiency_level="  ",
            )
        empty = (
            Samples()
            .history()
            .model_copy(update={"proficiency_level": None, "events": None})
        )
        assert empty.proficiency_level is None
        assert empty.events is None
        learner = Samples().learner_id()
        assert isinstance(learner.value, UUID)
