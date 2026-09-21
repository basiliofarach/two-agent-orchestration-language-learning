"""Locate the repository root from any test module."""

from pathlib import Path


class RepositoryPaths:
    """Walk parents until the workspace pyproject is found."""

    def root(self) -> Path:
        here = Path(__file__).resolve()
        for candidate in here.parents:
            marker = candidate / "pyproject.toml"
            members = candidate / "tutor-core"
            if marker.is_file() and members.is_dir():
                return candidate
        message = "repository root not found from test support module"
        raise RuntimeError(message)
