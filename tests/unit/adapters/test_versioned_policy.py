"""Versioned policy: the card in force, and publication that does not update."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from tests.contract.test_port_contracts import (
    PolicyArtifactPortContract,
    PolicyPublicationPortContract,
)
from tests.support.reversible_cipher import ReversibleCipher
from tests.support.samples import Samples
from tests.support.scripted_connection import ScriptedConnection

from tutor_api.adapters.frozen_clock import FrozenClock
from tutor_api.adapters.persistence.versioned_policy import (
    PolicyCardCodec,
    PolicyVersionMissing,
    PolicyVersionUnreadable,
    PolicyVersionWriter,
    VersionedPolicyCard,
)
from tutor_core.domain.policy.lineage import PolicyRuleLineage, PolicyRuleMeaningChanged
from tutor_core.domain.policy.policy_card import PolicyCard
from tutor_core.domain.ports.cipher import CipherPort
from tutor_core.domain.ports.policy_artifact import PolicyArtifactPort
from tutor_core.domain.ports.policy_publication import PolicyPublicationPort

_MARCH = datetime(2026, 3, 1, tzinfo=UTC)


class SealedRow:
    """One ``policy_version`` row, without ``effective_from``."""

    def __init__(self, cipher: CipherPort) -> None:
        self._codec = PolicyCardCodec(cipher)

    def of(self, card: PolicyCard) -> tuple[object, ...]:
        parameters = self._codec.insert_parameters(
            card,
            datetime(2026, 1, 1, tzinfo=UTC),
        )
        return (
            parameters["version"],
            parameters["allowed_actions"],
            parameters["denied_actions"],
            parameters["escalation_rules"],
            parameters["article_mappings"],
        )


class Wired:
    """The adapters with every collaborator handed in, as the container does."""

    def reader(
        self, connection: ScriptedConnection, clock: FrozenClock | None = None
    ) -> VersionedPolicyCard:
        return VersionedPolicyCard(
            connection,
            clock or FrozenClock(_MARCH),
            PolicyCardCodec(ReversibleCipher()),
        )

    def writer(self, connection: ScriptedConnection) -> PolicyVersionWriter:
        return PolicyVersionWriter(
            connection,
            PolicyCardCodec(ReversibleCipher()),
            PolicyRuleLineage(),
        )

    def stored(self) -> ScriptedConnection:
        return ScriptedConnection(
            (SealedRow(ReversibleCipher()).of(Samples().policy_card()),)
        )


class TestVersionedPolicyCardContract(PolicyArtifactPortContract):
    def port(self) -> PolicyArtifactPort:
        return Wired().reader(Wired().stored())


class TestPolicyVersionWriterContract(PolicyPublicationPortContract):
    def port(self) -> PolicyPublicationPort:
        return Wired().writer(ScriptedConnection())


class TestVersionedPolicyCard:
    async def test_current_uses_the_injected_clock(self) -> None:
        connection = Wired().stored()
        clock = FrozenClock(_MARCH)
        card = await Wired().reader(connection, clock).current()
        assert card == Samples().policy_card()
        assert connection.parameters[0]["as_of"] == clock.now()

    async def test_a_missing_version_raises_instead_of_a_default(self) -> None:
        port = Wired().reader(ScriptedConnection())
        with pytest.raises(PolicyVersionMissing, match="no policy version"):
            await port.current()
        with pytest.raises(PolicyVersionMissing, match="no policy version"):
            await port.version()

    async def test_an_unreadable_version_raises(self) -> None:
        row = ("policy-1", b"nope", b"nope", b"nope", b"nope")
        port = Wired().reader(ScriptedConnection((row,)))
        with pytest.raises(PolicyVersionUnreadable, match="cannot be read"):
            await port.current()

    def test_public_methods_are_current_and_version(self) -> None:
        public = [
            name
            for name in dir(VersionedPolicyCard)
            if not name.startswith("_") and callable(getattr(VersionedPolicyCard, name))
        ]
        assert public == ["current", "version"]


class TestPolicyCardCodec:
    def test_a_memoryview_round_trips(self) -> None:
        cipher = ReversibleCipher()
        codec = PolicyCardCodec(cipher)
        row = SealedRow(cipher).of(Samples().policy_card())
        sealed = row[1]
        assert isinstance(sealed, bytes)
        viewed = (row[0], memoryview(sealed), row[2], row[3], row[4])
        assert codec.open(viewed) == Samples().policy_card()

    def test_a_column_that_is_not_bytes_is_rejected(self) -> None:
        cipher = ReversibleCipher()
        row = ("policy-1", "clear", b"sealed:[]", b"sealed:[]", b"sealed:[]")
        with pytest.raises(ValueError, match="not ciphertext"):
            PolicyCardCodec(cipher).open(row)


class TestPolicyVersionWriter:
    async def test_publish_inserts_and_does_not_update(self) -> None:
        connection = ScriptedConnection()
        await (
            Wired()
            .writer(connection)
            .publish(
                Samples().policy_card(),
                datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        assert len(connection.statements) == 2
        assert connection.statements[1].lstrip().upper().startswith("INSERT")
        assert "UPDATE" not in connection.statements[1].upper()
        assert connection.parameters[1]["version"] == "policy-1"

    async def test_a_changed_rule_meaning_is_not_inserted(self) -> None:
        connection = Wired().stored()
        moved = (
            Samples()
            .policy_card()
            .allowed_actions[0]
            .model_copy(update={"statement": "open_web"})
        )
        later = (
            Samples()
            .policy_card()
            .model_copy(update={"version": "policy-2", "allowed_actions": (moved,)})
        )
        with pytest.raises(PolicyRuleMeaningChanged, match="changed meaning"):
            await (
                Wired()
                .writer(connection)
                .publish(
                    later,
                    datetime(2026, 6, 1, tzinfo=UTC),
                )
            )
        assert all(
            "INSERT" not in statement.upper() for statement in connection.statements
        )

    async def test_an_unreadable_stored_version_blocks_publication(self) -> None:
        row = ("policy-1", b"nope", b"nope", b"nope", b"nope")
        connection = ScriptedConnection((row,))
        with pytest.raises(PolicyVersionUnreadable, match="cannot be read"):
            await (
                Wired()
                .writer(connection)
                .publish(
                    Samples().policy_card().model_copy(update={"version": "policy-2"}),
                    datetime(2026, 6, 1, tzinfo=UTC),
                )
            )
        assert all(
            "INSERT" not in statement.upper() for statement in connection.statements
        )

    async def test_a_naive_instant_is_rejected(self) -> None:
        connection = ScriptedConnection()
        with pytest.raises(ValidationError):
            await (
                Wired()
                .writer(connection)
                .publish(
                    Samples().policy_card(),
                    datetime(2026, 1, 1),  # noqa: DTZ001 — the naive instant under test
                )
            )
        assert connection.statements == []

    async def test_an_offset_is_stored_as_utc(self) -> None:
        connection = ScriptedConnection()
        offset = timezone(timedelta(hours=2))
        await (
            Wired()
            .writer(connection)
            .publish(
                Samples().policy_card(),
                datetime(2026, 6, 1, 12, 0, tzinfo=offset),
            )
        )
        assert connection.parameters[1]["effective_from"] == datetime(
            2026, 6, 1, 10, 0, tzinfo=UTC
        )

    def test_public_methods_are_publish_only(self) -> None:
        public = [
            name
            for name in dir(PolicyVersionWriter)
            if not name.startswith("_") and callable(getattr(PolicyVersionWriter, name))
        ]
        assert public == ["publish"]
