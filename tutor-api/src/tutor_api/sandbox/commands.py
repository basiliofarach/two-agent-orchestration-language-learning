"""Compose, Alembic, and pytest argv for one sandbox run."""

import os
from pathlib import Path

from tutor_api.sandbox.identity import SandboxIdentity


class SandboxPaths:
    """``tutor-api/`` and the repository root, resolved from this package."""

    def __init__(self, api_root: Path) -> None:
        self._api_root = api_root

    @classmethod
    def from_here(cls) -> "SandboxPaths":
        """The tree this module is installed in."""
        return cls(Path(__file__).resolve().parents[3])

    def api_root(self) -> Path:
        """Where ``alembic.ini`` and the sandbox compose file live."""
        return self._api_root

    def repo_root(self) -> Path:
        """Where ``pytest`` collects ``tests/integration``."""
        return self._api_root.parent

    def compose_file(self) -> Path:
        """The compose file that does not interpolate the operator ``.env``."""
        return self._api_root / "docker-compose.sandbox.yml"


class SandboxEnvironment:
    """Process environment whose database settings are the sandbox only."""

    def __init__(self, identity: SandboxIdentity, base: dict[str, str]) -> None:
        self._identity = identity
        self._base = base

    def overlay(self) -> dict[str, str]:
        """``base`` with every database variable pointed at the sandbox.

        Pydantic settings prefer the process environment over ``.env``, so
        Alembic and pytest cannot fall through to the operator URL.
        ``COMPOSE_DISABLE_ENV_FILE`` stops Compose reading that file too.
        """
        env = dict(self._base)
        identity = self._identity
        env["COMPOSE_DISABLE_ENV_FILE"] = "1"
        env["DATABASE_URL"] = identity.alembic_url()
        env["APPLICATION_DATABASE_URL"] = identity.application_url()
        env["POSTGRES_USER"] = identity.user
        env["POSTGRES_PASSWORD"] = identity.password
        env["POSTGRES_DB"] = identity.database
        env["POSTGRES_HOST"] = identity.host
        env["POSTGRES_PORT"] = str(identity.port)
        env["POSTGRES_APP_USER"] = identity.app_user
        env["POSTGRES_APP_PASSWORD"] = identity.app_password
        env["TUTOR_SANDBOX_URL"] = identity.maintenance_url()
        return env

    def already_inside(self) -> bool:
        """True when this process was started by the sandbox runner."""
        return "TUTOR_SANDBOX_URL" in self._base


class SandboxCommands:
    """The four argv tuples, in the order the runner executes them."""

    def __init__(
        self,
        identity: SandboxIdentity,
        paths: SandboxPaths,
        python: str,
    ) -> None:
        self._identity = identity
        self._paths = paths
        self._python = python

    def up(self) -> tuple[str, ...]:
        """Start the sandbox and wait until its healthcheck passes."""
        return (
            *self._compose(),
            "up",
            "-d",
            "--wait",
            "--wait-timeout",
            "120",
        )

    def down(self) -> tuple[str, ...]:
        """Remove the sandbox project and its volumes."""
        return (*self._compose(), "down", "-v", "--remove-orphans")

    def migrate(self) -> tuple[str, ...]:
        """Apply ``upgrade head`` with the sandbox URL in the environment."""
        return (self._python, "-m", "alembic", "upgrade", "head")

    def check(self, command: tuple[str, ...] | None) -> tuple[str, ...]:
        """The integration suite, or the command a caller substituted."""
        if command is not None:
            return command
        return (
            self._python,
            "-m",
            "pytest",
            "tests/integration",
            "-q",
            "--tb=short",
            "-m",
            "not sandbox_lifecycle",
        )

    def _compose(self) -> tuple[str, ...]:
        return (
            "docker",
            "compose",
            "-p",
            self._identity.project,
            "-f",
            str(self._paths.compose_file()),
        )


class ProcessEnvironment:
    """The environment of this process. Tests pass a dict instead."""

    def values(self) -> dict[str, str]:
        """A copy, so a later overlay cannot mutate the process environment."""
        return dict(os.environ)
