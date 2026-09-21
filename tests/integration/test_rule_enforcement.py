"""Guard rails fire on committed violation fixtures (BE-01)."""

from __future__ import annotations

import shutil

from tests.support.command import GuardrailCommand
from tests.support.repository import RepositoryPaths


class TestRuleEnforcement:
    def test_clean_tree_satisfies_import_linter(self) -> None:
        root = RepositoryPaths().root()
        result = GuardrailCommand().run(
            ["uv", "run", "lint-imports"],
            cwd=root,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_dataclasses_import_fails_ruff_with_dec_0002(self) -> None:
        root = RepositoryPaths().root()
        fixture = (
            root / "tests" / "fixtures" / "rule_violations" / "import_dataclasses.py"
        )
        result = GuardrailCommand().run(
            ["uv", "run", "ruff", "check", str(fixture)],
            cwd=root,
        )
        combined = result.stdout + result.stderr
        assert result.returncode != 0
        assert "DEC-0002" in combined

    def test_fastapi_import_in_domain_fails_import_linter(self) -> None:
        root = RepositoryPaths().root()
        planted = (
            root
            / "tutor-core"
            / "src"
            / "tutor_core"
            / "domain"
            / "_be01_fastapi_violation.py"
        )
        fixture = (
            root
            / "tests"
            / "fixtures"
            / "rule_violations"
            / "domain_imports_fastapi.py"
        )
        shutil.copyfile(fixture, planted)
        try:
            result = GuardrailCommand().run(
                ["uv", "run", "lint-imports"],
                cwd=root,
            )
        finally:
            planted.unlink(missing_ok=True)
        combined = result.stdout + result.stderr
        assert result.returncode != 0
        assert "fastapi" in combined.lower()
