"""Deliberate violation: the harness must not import the system (DEC-0015)."""

import tutor_core

__all__ = ["tutor_core"]
