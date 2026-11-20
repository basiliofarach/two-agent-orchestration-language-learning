"""Reach Ollama only when the local runtime is up (DEC-0007).

The pin is the weights blob. ``/api/tags`` reports manifest digests, which
are not the weights, so the check reads each model's modelfile through the
same endpoint and resolver the API uses.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest
from tests.support.runtime_pin import RuntimePin

from tutor_api.adapters.llm.ollama import (
    ModelfileWeights,
    PinnedModelName,
    UrllibOllamaEndpoint,
)

_BASE = "http://127.0.0.1:11434"


class OllamaRuntime:
    """Whether the local runtime answers at all."""

    def is_reachable(self) -> bool:
        request = urllib.request.Request(f"{_BASE}/api/tags", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                return response.status == 200
        except (urllib.error.URLError, TimeoutError, OSError):
            return False

    def tags_body(self) -> dict[str, object]:
        """The raw ``/api/tags`` body. Other live tests list names from it."""
        request = urllib.request.Request(f"{_BASE}/api/tags", method="GET")
        with urllib.request.urlopen(request, timeout=5) as response:
            payload: object = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("ollama /api/tags must return an object")
        return payload


class TestPinnedOllamaRevision:
    @pytest.mark.requires_ollama
    def test_runtime_revision_matches_pin(self) -> None:
        if not OllamaRuntime().is_reachable():
            pytest.skip("Ollama is not running on localhost:11434")
        endpoint = UrllibOllamaEndpoint(_BASE, ModelfileWeights())
        weights = tuple((name, endpoint.weights(name)) for name in endpoint.names())
        name = PinnedModelName().resolve(RuntimePin().weights_sha(), weights)
        assert name
