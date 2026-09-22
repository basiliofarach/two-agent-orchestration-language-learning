"""Every project ships an .env.example, and no real .env is ever committed."""

import subprocess
import tomllib
from pathlib import Path

from tests.support.repository import RepositoryPaths


class WorkspaceProjects:
    """The repository root plus every uv workspace member."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def directories(self) -> tuple[Path, ...]:
        with (self._root / "pyproject.toml").open("rb") as handle:
            document = tomllib.load(handle)
        members = document["tool"]["uv"]["workspace"]["members"]
        return (self._root, *(self._root / member for member in members))


class TrackedFiles:
    """Paths git has under version control."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def names(self) -> tuple[str, ...]:
        result = subprocess.run(  # noqa: S603
            ["git", "ls-files"],  # noqa: S607
            cwd=self._root,
            capture_output=True,
            text=True,
            check=True,
        )
        return tuple(result.stdout.split())


class TestEnvExamples:
    def test_every_project_ships_an_example(self) -> None:
        root = RepositoryPaths().root()
        missing = [
            str(directory.relative_to(root) or ".")
            for directory in WorkspaceProjects(root).directories()
            if not (directory / ".env.example").is_file()
        ]
        assert missing == []

    def test_no_real_env_file_is_tracked(self) -> None:
        """A committed .env would publish the database credentials."""
        root = RepositoryPaths().root()
        committed = [
            name
            for name in TrackedFiles(root).names()
            if Path(name).name == ".env" or Path(name).name.startswith(".env.")
            if Path(name).name != ".env.example"
        ]
        assert committed == []

    def test_examples_carry_no_value_that_looks_generated(self) -> None:
        """An example holds placeholders, not a copied-out real secret."""
        root = RepositoryPaths().root()
        for directory in WorkspaceProjects(root).directories():
            example = directory / ".env.example"
            for line in example.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                _, _, value = stripped.partition("=")
                assert len(value) < 64, f"{example}: {stripped!r} looks like a secret"
