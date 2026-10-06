"""The sandbox compose project comes up, and it is not the operator database."""

import os
import subprocess
import sys

import pytest

from tutor_api.sandbox.commands import (
    SandboxCommands,
    SandboxEnvironment,
    SandboxPaths,
)
from tutor_api.sandbox.identity import SandboxIdentity
from tutor_api.sandbox.orchestrator import ProcessLaunch, SandboxOrchestrator


class ProjectContainers:
    """Containers and volumes of one compose project."""

    def __init__(self, project: str) -> None:
        self._project = project

    def ids(self) -> str:
        """Every container id, running or stopped."""
        completed = subprocess.run(
            ["docker", "compose", "-p", self._project, "ps", "-aq"],
            check=False,
            capture_output=True,
            text=True,
        )
        return completed.stdout

    def volumes(self) -> tuple[str, ...]:
        """Volume names that belong to this project."""
        completed = subprocess.run(
            ["docker", "volume", "ls", "-q"],
            check=False,
            capture_output=True,
            text=True,
        )
        prefix = f"{self._project}_"
        return tuple(
            line for line in completed.stdout.splitlines() if line.startswith(prefix)
        )


@pytest.mark.sandbox_lifecycle
class TestSandboxLifecycle:
    def test_a_failing_check_removes_the_sandbox_and_leaves_the_operator(
        self,
    ) -> None:
        identity = SandboxIdentity()
        if SandboxEnvironment(identity, dict(os.environ)).already_inside():
            pytest.skip("this process is already the sandbox suite")
        operator = ProjectContainers("tutor")
        sandbox = ProjectContainers(identity.project)
        before_ids = operator.ids()
        before_volumes = operator.volumes()
        paths = SandboxPaths.from_here()
        code = SandboxOrchestrator(
            ProcessLaunch(),
            SandboxCommands(identity, paths, sys.executable),
            SandboxEnvironment(identity, dict(os.environ)),
            paths,
        ).run((sys.executable, "-c", "import sys; sys.exit(1)"))
        assert code == 1
        assert sandbox.ids().strip() == ""
        assert sandbox.volumes() == ()
        assert operator.ids() == before_ids
        assert operator.volumes() == before_volumes
