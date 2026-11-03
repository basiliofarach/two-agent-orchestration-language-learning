"""Stable identifiers. The same persona and document keep the same ids across builds."""

from uuid import NAMESPACE_DNS, UUID, uuid5


class SimulationNamespace:
    """``uuid5`` under one namespace the harness owns."""

    def document_id(self, source_id: str, item_key: str) -> UUID:
        """The document id for one source item. It does not depend on the clock."""
        return uuid5(self._value(), f"{source_id}/{item_key}")

    def learner_id(self, persona_id: str) -> UUID:
        """The learner id for one persona. The pseudonym stays the persona id."""
        return uuid5(self._value(), persona_id)

    def _value(self) -> UUID:
        return uuid5(NAMESPACE_DNS, "tutor-sim.thesis")
