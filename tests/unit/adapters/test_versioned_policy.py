"""Versioned policy: the card in force, and publication that does not update."""

import json
from collections.abc import Mapping
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
from tutor_core.domain.policy.policy_card import ArticleMapping, PolicyCard, PolicyRule
from tutor_core.domain.ports.cipher import CipherPort
from tutor_core.domain.ports.policy_artifact import PolicyArtifactPort
from tutor_core.domain.ports.policy_publication import PolicyPublicationPort

_MARCH = datetime(2026, 3, 1, tzinfo=UTC)


class SealedArticleMapping:
    """One article mapping, sealed the way a policy column stores it."""

    def ciphertext(self, cipher: CipherPort) -> bytes:
        mapping = ArticleMapping(article="12", locus="per-turn audit log")
        encoded = json.dumps(
            [mapping.model_dump(mode="json")],
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return cipher.encrypt(encoded.encode("utf-8"))


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


class SecondRead(ScriptedConnection):
    """The first fetch is the card in force. A later fetch is a newer publication."""

    def __init__(self, first: tuple[object, ...], later: tuple[object, ...]) -> None:
        super().__init__((first,))
        self._later = later
        self.reads = 0

    async def fetch_one(
        self,
        statement: str,
        parameters: Mapping[str, object],
    ) -> tuple[object, ...] | None:
        self._record(statement, parameters)
        self.reads += 1
        if self.reads == 1:
            return self._rows[0]
        return self._later


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

    async def test_version_returns_the_card_already_selected(self) -> None:
        cipher = ReversibleCipher()
        first = SealedRow(cipher).of(Samples().policy_card())
        later = SealedRow(cipher).of(
            Samples().policy_card().model_copy(update={"version": "policy-2"})
        )
        connection = SecondRead(first, later)
        port = Wired().reader(connection)
        assert (await port.current()).version == "policy-1"
        assert await port.version() == "policy-1"
        assert connection.reads == 1

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

    def test_a_legacy_string_list_opens_as_rules(self) -> None:
        cipher = ReversibleCipher()
        codec = PolicyCardCodec(cipher)
        row = (
            "policy-1",
            cipher.encrypt(b'["retrieve_vetted"]'),
            cipher.encrypt(b'["open_web"]'),
            cipher.encrypt(b'["pause_routes_to_tutor"]'),
            SealedArticleMapping().ciphertext(cipher),
        )
        card = codec.open(row)
        assert card.version == "policy-1"
        assert card.allowed_actions[0].policy_rule_id == "retrieve_vetted"
        assert card.allowed_actions[0].statement == "retrieve_vetted"
        assert card.allowed_actions[0].article is None
        assert card.denied_actions[0].statement == "open_web"
        assert card.escalation_rules[0].statement == "pause_routes_to_tutor"
        assert card.article_mappings[0].article == "12"

    def test_a_rule_column_that_is_not_a_list_is_rejected(self) -> None:
        cipher = ReversibleCipher()
        row = (
            "policy-1",
            cipher.encrypt(b'{"policy_rule_id":"retrieve-vetted"}'),
            cipher.encrypt(b"[]"),
            cipher.encrypt(b"[]"),
            cipher.encrypt(b"[]"),
        )
        with pytest.raises(ValueError, match="not a list"):
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
        assert len(connection.statements) == 3
        assert connection.statements[2].lstrip().upper().startswith("INSERT")
        assert "UPDATE" not in connection.statements[2].upper()
        assert connection.parameters[2]["version"] == "policy-1"

    async def test_publish_runs_serializable_before_reading_the_history(
        self,
    ) -> None:
        connection = ScriptedConnection()
        await (
            Wired()
            .writer(connection)
            .publish(Samples().policy_card(), datetime(2026, 1, 1, tzinfo=UTC))
        )
        assert connection.statements[0] == (
            "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"
        )
        assert "FROM policy_version" in connection.statements[1]

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
        assert connection.parameters[2]["effective_from"] == datetime(
            2026, 6, 1, 10, 0, tzinfo=UTC
        )

    async def test_a_legacy_action_keeps_its_meaning_until_the_article_is_set(
        self,
    ) -> None:
        cipher = ReversibleCipher()
        legacy = (
            "policy-1",
            cipher.encrypt(b'["retrieve_vetted"]'),
            cipher.encrypt(b"[]"),
            cipher.encrypt(b"[]"),
            SealedArticleMapping().ciphertext(cipher),
        )
        connection = ScriptedConnection((legacy,))
        opened = PolicyCardCodec(cipher).open(legacy)
        await (
            Wired()
            .writer(connection)
            .publish(
                opened.model_copy(update={"version": "policy-2"}),
                datetime(2026, 6, 1, tzinfo=UTC),
            )
        )
        assert connection.statements[2].lstrip().upper().startswith("INSERT")
        assigned = PolicyRule(
            policy_rule_id="retrieve_vetted",
            statement="retrieve_vetted",
            article="10",
        )
        with pytest.raises(PolicyRuleMeaningChanged, match="changed meaning"):
            await (
                Wired()
                .writer(ScriptedConnection((legacy,)))
                .publish(
                    opened.model_copy(
                        update={"version": "policy-3", "allowed_actions": (assigned,)}
                    ),
                    datetime(2026, 7, 1, tzinfo=UTC),
                )
            )

    def test_public_methods_are_publish_only(self) -> None:
        public = [
            name
            for name in dir(PolicyVersionWriter)
            if not name.startswith("_") and callable(getattr(PolicyVersionWriter, name))
        ]
        assert public == ["publish"]
