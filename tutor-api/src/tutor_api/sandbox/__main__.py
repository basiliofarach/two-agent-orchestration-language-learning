"""``python -m tutor_api.sandbox`` from ``tutor-api/``."""

import sys

from tutor_api.sandbox.commands import (
    ProcessEnvironment,
    SandboxCommands,
    SandboxEnvironment,
    SandboxPaths,
)
from tutor_api.sandbox.identity import SandboxIdentity
from tutor_api.sandbox.orchestrator import ProcessLaunch, SandboxOrchestrator


class SandboxModule:
    """The module entry and the sandbox's composition root.

    The orchestrator receives its collaborators; it does not build them
    (rule 3). This is a developer command outside the application graph,
    so it is wired here rather than in ``tutor_api/di/``.
    """

    @staticmethod
    def main() -> None:
        """Exit with the sandbox run's status."""
        identity = SandboxIdentity()
        paths = SandboxPaths.from_here()
        orchestrator = SandboxOrchestrator(
            ProcessLaunch(),
            SandboxCommands(identity, paths, sys.executable),
            SandboxEnvironment(identity, ProcessEnvironment().values()),
            paths,
        )
        raise SystemExit(orchestrator.run())


if __name__ == "__main__":
    SandboxModule.main()
