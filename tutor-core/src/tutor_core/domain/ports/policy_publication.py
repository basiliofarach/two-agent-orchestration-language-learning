"""Publish a policy version. Reading the version in force is a different port."""

from abc import ABC, abstractmethod
from datetime import datetime

from tutor_core.domain.policy.policy_card import PolicyCard


class PolicyPublicationPort(ABC):
    """Append one policy version (REQ-POLICY).

    Scope boundary: publication only. No update and no delete. Selecting
    the version in force is ``PolicyArtifactPort``. A ``policy_rule_id``
    whose category, statement, or article changes is rejected, so an id
    stays stable until the rule's meaning changes. Async because it writes
    on an enlisted connection (DEC-0014).
    """

    @abstractmethod
    async def publish(self, card: PolicyCard, effective_from: datetime) -> None:
        """Insert ``card``, in force from ``effective_from``. Fail closed."""
        raise NotImplementedError  # pragma: no cover
