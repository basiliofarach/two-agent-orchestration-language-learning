"""Read committed runtime pins (DEC-0006, DEC-0007)."""

from __future__ import annotations

import tomllib
from pathlib import Path

from tests.support.repository import RepositoryPaths


class RuntimePin:
    """Typed view over config/runtime.toml."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root if root is not None else RepositoryPaths().root()

    def _document(self) -> dict[str, object]:
        path = self._root / "config" / "runtime.toml"
        with path.open("rb") as handle:
            loaded = tomllib.load(handle)
        if not isinstance(loaded, dict):
            raise TypeError("runtime.toml must be a table")
        return loaded

    def postgres_image(self) -> str:
        postgres = self._document()["postgres"]
        if not isinstance(postgres, dict):
            raise TypeError("postgres pin must be a table")
        image = postgres["image"]
        version = postgres["version"]
        digest = postgres["image_digest"]
        if not isinstance(image, str):
            raise TypeError("image must be a string")
        if not isinstance(version, str):
            raise TypeError("version must be a string")
        if not isinstance(digest, str):
            raise TypeError("image_digest must be a string")
        return f"{image}:{version}@sha256:{digest}"

    def weights_sha(self) -> str:
        model = self._document()["model"]
        if not isinstance(model, dict):
            raise TypeError("model pin must be a table")
        value = model["weights_sha"]
        if not isinstance(value, str):
            raise TypeError("weights_sha must be a string")
        return value

    def huggingface_commit(self) -> str:
        model = self._document()["model"]
        if not isinstance(model, dict):
            raise TypeError("model pin must be a table")
        value = model["huggingface_commit"]
        if not isinstance(value, str):
            raise TypeError("huggingface_commit must be a string")
        return value

    def ollama_version(self) -> str:
        model = self._document()["model"]
        if not isinstance(model, dict):
            raise TypeError("model pin must be a table")
        value = model["ollama_version"]
        if not isinstance(value, str):
            raise TypeError("ollama_version must be a string")
        return value
