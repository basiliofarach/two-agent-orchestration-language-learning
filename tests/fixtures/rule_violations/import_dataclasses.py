from dataclasses import dataclass


@dataclass
class Forbidden:
    """Deliberate DEC-0002 violation for the guard-rail test."""

    name: str
