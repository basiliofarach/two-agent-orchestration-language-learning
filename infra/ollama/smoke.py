"""One completion from the local model whose weights are the pin (DEC-0007).

Ollama cannot generate by a weights digest: ``/api/generate`` takes a model
name. The smoke therefore resolves the name the way the API does. It lists
the local models, reads each modelfile's ``FROM`` blob, and keeps the single
match. A missing or doubled match fails closed.
"""

from __future__ import annotations

import sys
from typing import TextIO

from tests.support.runtime_pin import RuntimePin

from tutor_api.adapters.llm.ollama import (
    ModelfileWeights,
    OllamaEndpoint,
    PinnedModelName,
    UrllibOllamaEndpoint,
)
from tutor_core.domain.models.safety import DecodingParams


class LocalModelSmoke:
    """One short completion from the pinned weights. No network egress."""

    def __init__(self, endpoint: OllamaEndpoint, pin: str) -> None:
        self._endpoint = endpoint
        self._pin = pin

    def complete(self, prompt: str = "Reply with the single word ok.") -> str:
        """The resolved model's reply. A blank reply is a failure."""
        name = self.model_name()
        text = self._endpoint.generate(
            name, prompt, DecodingParams(temperature=0.0, top_p=1.0, max_tokens=512)
        )
        if not text.strip():
            msg = "smoke prompt returned no completion"
            raise RuntimeError(msg)
        return text

    def model_name(self) -> str:
        """The single local model whose weights blob is the pin."""
        weights = tuple(
            (name, self._endpoint.weights(name)) for name in self._endpoint.names()
        )
        return PinnedModelName().resolve(self._pin, weights)


class SmokeMain:
    """Print which model answered and its reply."""

    def __init__(self, smoke: LocalModelSmoke, output: TextIO) -> None:
        self._smoke = smoke
        self._output = output

    def __call__(self) -> int:
        try:
            name = self._smoke.model_name()
        except ValueError:
            self._output.write(
                "no local Ollama model has the pinned weights; "
                "run `ollama pull qwen3:8b` and check config/runtime.toml\n"
            )
            return 1
        reply = self._smoke.complete().strip().splitlines()[-1]
        self._output.write(f"{name} (pinned weights) replied: {reply}\n")
        return 0


if __name__ == "__main__":
    endpoint = UrllibOllamaEndpoint("http://127.0.0.1:11434", ModelfileWeights())
    smoke = LocalModelSmoke(endpoint, RuntimePin().weights_sha())
    raise SystemExit(SmokeMain(smoke, sys.stdout)())
