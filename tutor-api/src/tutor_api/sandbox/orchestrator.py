"""Bring up a throwaway Postgres, migrate it, test, and always remove it."""

import subprocess
from pathlib import Path

from tutor_api.sandbox.commands import (
    SandboxCommands,
    SandboxEnvironment,
    SandboxPaths,
)


class ProcessLaunch:
    """One subprocess. ``check`` is false so the caller can tear down after."""

    def run(
        self,
        command: tuple[str, ...],
        env: dict[str, str],
        cwd: Path,
    ) -> int:
        """Run ``command`` in ``cwd``. Return its status. Do not raise."""
        print("$", " ".join(command), flush=True)
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            env=env,
            check=False,
        )
        return completed.returncode


class SandboxOrchestrator:
    """One sandbox run. Teardown is not a later stage the caller can skip.

    ``prepare`` / ``execute`` / ``finalise`` would leave the containers up
    when migrate or pytest fails, because ``finalise`` is only reached on
    success. The ``finally`` below is the teardown, and it runs first in
    the sense that it is armed before migrate and before pytest.
    """

    def __init__(
        self,
        launch: ProcessLaunch,
        commands: SandboxCommands,
        environment: SandboxEnvironment,
        paths: SandboxPaths,
    ) -> None:
        self._launch = launch
        self._commands = commands
        self._environment = environment
        self._paths = paths

    def run(self, check: tuple[str, ...] | None = None) -> int:
        """Clear, up, migrate, run ``check`` or the integration suite, then down.

        The clear is the same ``down -v`` as the teardown. A run killed
        before its ``finally`` leaves the volume behind; ``up`` would reuse
        it, the init scripts would not run, and ``upgrade head`` would find
        the database already at head and pass without having migrated a
        fresh one. A failing step still removes the project and its
        volumes. The status returned is the first failure, or the
        teardown's status when the steps themselves passed.
        """
        env = self._environment.overlay()
        code = 1
        try:
            code = self._launch.run(
                self._commands.down(),
                env,
                self._paths.api_root(),
            )
            if code == 0:
                code = self._launch.run(
                    self._commands.up(),
                    env,
                    self._paths.api_root(),
                )
            if code == 0:
                code = self._launch.run(
                    self._commands.migrate(),
                    env,
                    self._paths.api_root(),
                )
            if code == 0:
                code = self._launch.run(
                    self._commands.check(check),
                    env,
                    self._paths.repo_root(),
                )
        finally:
            down = self._launch.run(
                self._commands.down(),
                env,
                self._paths.api_root(),
            )
        if code == 0:
            return down
        return code
