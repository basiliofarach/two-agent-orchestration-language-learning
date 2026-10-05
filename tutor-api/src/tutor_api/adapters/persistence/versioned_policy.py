"""Read and publish the versioned policy card (REQ-POLICY)."""

import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict, ValidationError

from tutor_core.domain.models.timestamps import AwareDatetime
from tutor_core.domain.policy.lineage import PolicyRuleLineage
from tutor_core.domain.policy.policy_card import (
    ArticleMapping,
    PolicyCard,
    PolicyRule,
)
from tutor_core.domain.ports.cipher import CipherPort
from tutor_core.domain.ports.clock import ClockPort
from tutor_core.domain.ports.policy_artifact import PolicyArtifactPort
from tutor_core.domain.ports.policy_publication import PolicyPublicationPort
from tutor_core.domain.ports.unit_of_work import TransactionConnection


class PolicyVersionMissing(Exception):
    """No policy version is in force at the instant asked for."""


class PolicyVersionUnreadable(Exception):
    """A stored version cannot be decrypted or does not validate."""


class EffectiveInstant(BaseModel):
    """The instant a published version takes effect, normalised to UTC."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    instant: AwareDatetime


class PolicyCardCodec:
    """Ciphertext JSON for the four policy columns (DEC-0012)."""

    def __init__(self, cipher: CipherPort) -> None:
        self._cipher = cipher

    def insert_parameters(
        self,
        card: PolicyCard,
        effective_from: datetime,
    ) -> dict[str, object]:
        """Bound values for one ``policy_version`` insert."""
        return {
            "version": card.version,
            "allowed_actions": self._seal_rules(card.allowed_actions),
            "denied_actions": self._seal_rules(card.denied_actions),
            "escalation_rules": self._seal_rules(card.escalation_rules),
            "article_mappings": self._seal_mappings(card.article_mappings),
            "effective_from": effective_from,
        }

    def open(self, row: tuple[object, ...]) -> PolicyCard:
        """Decrypt one selected row into a card. Fail closed on garbage."""
        return PolicyCard(
            version=str(row[0]),
            allowed_actions=self._open_rules(row[1]),
            denied_actions=self._open_rules(row[2]),
            escalation_rules=self._open_rules(row[3]),
            article_mappings=self._open_mappings(row[4]),
        )

    def _seal_rules(self, rules: tuple[PolicyRule, ...]) -> bytes:
        payload = [rule.model_dump(mode="json") for rule in rules]
        return self._cipher.encrypt(self._canonical(payload))

    def _seal_mappings(self, mappings: tuple[ArticleMapping, ...]) -> bytes:
        payload = [item.model_dump(mode="json") for item in mappings]
        return self._cipher.encrypt(self._canonical(payload))

    def _open_rules(self, value: object) -> tuple[PolicyRule, ...]:
        payload = json.loads(self._cipher.decrypt(self._bytes(value)))
        if not isinstance(payload, list):
            msg = "policy rules are not a list"
            raise ValueError(msg)
        return tuple(PolicyRule.model_validate(item) for item in payload)

    def _open_mappings(self, value: object) -> tuple[ArticleMapping, ...]:
        payload = json.loads(self._cipher.decrypt(self._bytes(value)))
        return tuple(ArticleMapping.model_validate(item) for item in payload)

    def _bytes(self, value: object) -> bytes:
        if isinstance(value, bytes):
            return value
        if isinstance(value, bytearray | memoryview):
            return bytes(value)
        msg = "policy column is not ciphertext"
        raise ValueError(msg)

    def _canonical(self, value: object) -> bytes:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")


class VersionedPolicyCard(PolicyArtifactPort):
    """The policy version in force at the injected clock (REQ-POLICY).

    ``current()`` is the latest row whose ``effective_from`` is at or before
    that instant. A missing or unreadable version raises. There is no
    built-in default card. Reads run on the request's enlisted connection
    (DEC-0014).
    """

    _LATEST = """
        SELECT version, allowed_actions, denied_actions, escalation_rules,
               article_mappings
        FROM policy_version
        WHERE effective_from <= :as_of
        ORDER BY effective_from DESC
        LIMIT 1
        """

    def __init__(
        self,
        connection: TransactionConnection,
        clock: ClockPort,
        codec: PolicyCardCodec,
    ) -> None:
        self._connection = connection
        self._clock = clock
        self._codec = codec

    async def current(self) -> PolicyCard:
        """Return the card in force now. Raise when none is."""
        row = await self._connection.fetch_one(
            self._LATEST, {"as_of": self._clock.now()}
        )
        if row is None:
            raise PolicyVersionMissing("no policy version is in force")
        try:
            return self._codec.open(row)
        except (ValueError, ValidationError) as exc:
            raise PolicyVersionUnreadable("policy version cannot be read") from exc

    async def version(self) -> str:
        """The version string a turn records when it starts."""
        return (await self.current()).version


class PolicyVersionWriter(PolicyPublicationPort):
    """Insert one policy version. Rows already stored are not updated."""

    _EVERY = """
        SELECT version, allowed_actions, denied_actions, escalation_rules,
               article_mappings
        FROM policy_version
        ORDER BY effective_from
        """

    _INSERT = """
        INSERT INTO policy_version (
            version, allowed_actions, denied_actions, escalation_rules,
            article_mappings, effective_from
        ) VALUES (
            :version, :allowed_actions, :denied_actions,
            :escalation_rules, :article_mappings, :effective_from
        )
        """

    def __init__(
        self,
        connection: TransactionConnection,
        codec: PolicyCardCodec,
        lineage: PolicyRuleLineage,
    ) -> None:
        self._connection = connection
        self._codec = codec
        self._lineage = lineage

    async def publish(self, card: PolicyCard, effective_from: datetime) -> None:
        """Insert ``card`` if its rule ids still mean what they meant."""
        stamped = EffectiveInstant(instant=effective_from).instant
        rows = await self._connection.fetch_all(self._EVERY, {})
        try:
            existing = tuple(self._codec.open(row) for row in rows)
        except (ValueError, ValidationError) as exc:
            raise PolicyVersionUnreadable(
                "stored policy version cannot be read"
            ) from exc
        self._lineage.require_stable(existing, card)
        await self._connection.execute(
            self._INSERT, self._codec.insert_parameters(card, stamped)
        )
