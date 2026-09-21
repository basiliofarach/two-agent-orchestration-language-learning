"""Pinned SHAs are hex, never a tag (DEC-0007)."""

from __future__ import annotations

import re
from pathlib import Path

from tests.support.repository import RepositoryPaths
from tests.support.runtime_pin import RuntimePin

_SHA = re.compile(r"^[0-9a-f]{12,64}$")
_FORBIDDEN_TAGS = ("qwen3:8b", "qwen3:latest", ":latest")
_CONFIG_SUFFIXES = {".toml", ".yml", ".yaml", ".lock"}
_CONFIG_NAMES = {"Makefile", "docker-compose.yml", "Justfile"}


class TestModelRevisionPin:
    def test_weights_sha_is_hex(self) -> None:
        assert _SHA.fullmatch(RuntimePin().weights_sha()) is not None

    def test_huggingface_commit_is_hex(self) -> None:
        assert _SHA.fullmatch(RuntimePin().huggingface_commit()) is not None

    def test_postgres_digest_is_hex(self) -> None:
        digest = RuntimePin().postgres_image().rsplit(":", maxsplit=1)[-1]
        assert _SHA.fullmatch(digest) is not None

    def test_ollama_version_is_recorded(self) -> None:
        version = RuntimePin().ollama_version()
        assert re.fullmatch(r"\d+\.\d+\.\d+", version) is not None

    def test_configuration_files_do_not_name_a_model_tag(self) -> None:
        root = RepositoryPaths().root()
        offenders: list[str] = []
        for path in self._configuration_files(root):
            text = path.read_text(encoding="utf-8")
            for tag in _FORBIDDEN_TAGS:
                if tag in text:
                    offenders.append(f"{path.relative_to(root)} contains {tag}")
        assert offenders == []

    def _configuration_files(self, root: Path) -> list[Path]:
        files: list[Path] = []
        search_roots = (
            root / "config",
            root / "infra",
        )
        named = [
            root / "tutor-api" / "docker-compose.yml",
            root / "tutor-api" / "Makefile",
            root / "pyproject.toml",
        ]
        for candidate in named:
            if candidate.is_file():
                files.append(candidate)
        for search_root in search_roots:
            if not search_root.exists():
                continue
            for path in search_root.rglob("*"):
                if path.is_file() and (
                    path.suffix in _CONFIG_SUFFIXES or path.name in _CONFIG_NAMES
                ):
                    files.append(path)
        return files
