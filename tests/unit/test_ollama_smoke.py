"""The model smoke finds the pinned weights by name, as the API does."""

import io

import pytest
from infra.ollama.smoke import LocalModelSmoke, SmokeMain

from tutor_api.adapters.llm.ollama import OllamaEndpoint
from tutor_core.domain.models.safety import DecodingParams

_PIN = "a" * 64


class StubEndpoint(OllamaEndpoint):
    def __init__(
        self, models: dict[str, str], reply: str = "<think>\n</think>\nok"
    ) -> None:
        self._models = models
        self._reply = reply
        self.asked: list[str] = []

    def names(self) -> tuple[str, ...]:
        return tuple(self._models)

    def weights(self, model_name: str) -> str:
        return self._models[model_name]

    def generate(self, model_name: str, prompt: str, decoding: DecodingParams) -> str:
        self.asked.append(model_name)
        return self._reply


class TestLocalModelSmoke:
    def test_the_model_with_the_pinned_weights_answers(self) -> None:
        endpoint = StubEndpoint({"mistral:7b": "b" * 64, "qwen3:8b": _PIN})
        output = io.StringIO()
        assert SmokeMain(LocalModelSmoke(endpoint, _PIN), output)() == 0
        assert endpoint.asked == ["qwen3:8b"]
        assert output.getvalue() == "qwen3:8b (pinned weights) replied: ok\n"

    def test_no_pinned_model_is_reported_not_raised(self) -> None:
        endpoint = StubEndpoint({"mistral:7b": "b" * 64})
        output = io.StringIO()
        assert SmokeMain(LocalModelSmoke(endpoint, _PIN), output)() == 1
        assert "ollama pull qwen3:8b" in output.getvalue()
        assert endpoint.asked == []

    def test_a_blank_reply_fails(self) -> None:
        endpoint = StubEndpoint({"qwen3:8b": _PIN}, reply="  ")
        with pytest.raises(RuntimeError, match="no completion"):
            LocalModelSmoke(endpoint, _PIN).complete()
