"""Operator entry. ``build`` is still refused; the other commands run."""

from typing import TextIO

from tutor_sim.composition import RoleUnpinned, SimulationCompositionRoot

_USAGE = 2


class SimulationCli:
    """``build | realise | freeze | verify | run | report``.

    A known command wires the harness, so a configuration fault surfaces now.
    ``build`` still fails: an exit of 0 would read as a finished fetch.
    """

    _COMMANDS = frozenset({"build", "realise", "freeze", "verify", "run", "report"})

    def __init__(self, root: SimulationCompositionRoot, errors: TextIO) -> None:
        self._root = root
        self._errors = errors

    def main(self, argv: list[str]) -> int:
        """Wire the harness for a known command. An unknown command is a usage error."""
        if not argv or argv[0] not in self._COMMANDS:
            return _USAGE
        try:
            wired = self._root.wire(self._errors)
        except RoleUnpinned as exc:
            self._errors.write(f"tutor_sim: {exc}\n")
            return 1
        try:
            return wired.commands.dispatch(argv[0])
        finally:
            wired.close()
