"""Qwen3 decodes without its thinking phase, and the audit says so.

At temperature 0 the thinking phase used the whole token budget and the
answer came back empty. ``think`` is recorded with the other decoding
parameters so a turn and its replay name the mode that produced them.
``None`` is a record sealed before the field existed.
"""

import pytest
from pydantic import ValidationError
from tests.support.samples import Samples
from tests.unit.adapters.test_prompt_and_model import Endpoint, LocalOllama
from tests.unit.application.test_evidence_exhibits import ReplacingRedactor

from tutor_api.evidence.catalogue import ExhibitResult
from tutor_api.evidence.project import ExcerptProjector
from tutor_api.prototype import PrototypeCopy
from tutor_core.domain.audit.record_hash import AuditRecordHash
from tutor_core.domain.models.safety import DecodingParams


def _params(think: bool | None) -> DecodingParams:
    return DecodingParams(temperature=0.0, top_p=1.0, max_tokens=64, think=think)


class TestDecodingParams:
    def test_the_thinking_mode_is_unrecorded_by_default(self) -> None:
        assert DecodingParams(temperature=0.0, top_p=1.0, max_tokens=64).think is None

    def test_the_thinking_mode_is_a_boolean(self) -> None:
        assert _params(False).think is False
        assert _params(True).think is True
        with pytest.raises(ValidationError):
            DecodingParams.model_validate(
                {"temperature": 0.0, "top_p": 1.0, "max_tokens": 64, "think": "x"}
            )

    def test_the_prototype_decodes_without_thinking_and_room_for_a_paragraph(
        self,
    ) -> None:
        decoding = PrototypeCopy().decoding()
        assert decoding.think is False
        assert decoding.max_tokens == 512
        assert decoding.temperature == 0.0


class TestRecordHash:
    def _record(self, think: bool | None):  # type: ignore[no-untyped-def]
        return (
            Samples()
            .audit_record()
            .model_copy(update={"decoding_params": _params(think)})
        )

    def test_a_record_sealed_before_the_field_hashes_without_it(self) -> None:
        canonical = AuditRecordHash().canonical(self._record(None))
        assert '"think"' not in canonical
        assert '"max_tokens":64' in canonical

    def test_a_recorded_mode_is_covered_by_the_hash(self) -> None:
        hasher = AuditRecordHash()
        off = hasher.canonical(self._record(False))
        assert '"think":false' in off
        assert hasher.digest(self._record(False)) != hasher.digest(self._record(None))
        assert hasher.digest(self._record(False)) != hasher.digest(self._record(True))


class TestOllamaRequest:
    def _sent(self, think: bool | None) -> dict[str, object]:
        server = LocalOllama()
        base = server.start({"models": []}, {"response": "hola"})
        try:
            Endpoint().at(base + "/").generate("qwen3:8b", "prompt", _params(think))
            path, body = server.requests()[-1]
        finally:
            server.stop()
        assert path == "/api/generate"
        assert isinstance(body, dict)
        return body

    def test_a_recorded_mode_is_sent_to_ollama(self) -> None:
        assert self._sent(False)["think"] is False
        assert self._sent(True)["think"] is True

    def test_an_unrecorded_mode_leaves_ollama_its_default(self) -> None:
        assert "think" not in self._sent(None)


class TestEvidenceExcerpt:
    def test_the_evidence_pack_shows_the_thinking_mode(self) -> None:
        record = (
            Samples()
            .audit_record()
            .model_copy(update={"decoding_params": _params(False)})
        )
        body = ExcerptProjector(ReplacingRedactor()).project(
            ExhibitResult(records=(record,)), ()
        )
        decoding = body.turns[0].decoding_params
        assert decoding is not None
        assert decoding.think is False
