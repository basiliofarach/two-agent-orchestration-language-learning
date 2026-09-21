"""Reach Ollama only when the local runtime is up (DEC-0007)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest
from tests.support.runtime_pin import RuntimePin


class OllamaRuntime:
    """Minimal client for the local Ollama HTTP API."""

    def __init__(self, base_url: str = "http://127.0.0.1:11434") -> None:
        self._base_url = base_url

    def is_reachable(self) -> bool:
        request = urllib.request.Request(f"{self._base_url}/api/tags", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                return response.status == 200
        except (urllib.error.URLError, TimeoutError, OSError):
            return False

    def tags_body(self) -> dict[str, object]:
        request = urllib.request.Request(f"{self._base_url}/api/tags", method="GET")
        with urllib.request.urlopen(request, timeout=5) as response:
            payload: object = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("ollama /api/tags must return an object")
        return payload


class TestPinnedOllamaRevision:
    @pytest.mark.requires_ollama
    def test_runtime_revision_matches_pin(self) -> None:
        runtime = OllamaRuntime()
        if not runtime.is_reachable():
            pytest.skip("Ollama is not running on localhost:11434")
        pin = RuntimePin().weights_sha()
        body = runtime.tags_body()
        models = body.get("models", [])
        if not isinstance(models, list):
            raise TypeError("models must be a list")
        digests = []
        for model in models:
            if isinstance(model, dict) and isinstance(model.get("digest"), str):
                digests.append(model["digest"])
        combined = " ".join(digests)
        assert pin in combined
