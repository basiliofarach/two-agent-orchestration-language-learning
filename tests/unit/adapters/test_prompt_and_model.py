"""Fixed template, scripted model, and the pinned Ollama adapter."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from tests.contract.test_port_contracts import (
    LanguageModelPortContract,
    PromptTemplatePortContract,
)
from tests.support.runtime_pin import RuntimePin
from tests.support.samples import Samples
from tests.support.scripted_model import ScriptedLanguageModel

from tutor_api.adapters.llm.fixed_prompt import FixedPromptTemplate
from tutor_api.adapters.llm.ollama import (
    LocalOllamaUrl,
    ModelfileWeights,
    ModelRevision,
    OllamaEndpoint,
    OllamaLanguageModel,
    PinnedModelName,
    PinnedRevision,
    UrllibOllamaEndpoint,
)
from tutor_api.container import HistoryFieldSetting
from tutor_api.prototype import PrototypeCopy
from tutor_core.domain.models.learner import HistoryFieldSet
from tutor_core.domain.models.safety import DecodingParams
from tutor_core.domain.ports.language_model import LanguageModelPort
from tutor_core.domain.ports.prompt_template import PromptTemplatePort


class Template:
    def build(self) -> FixedPromptTemplate:
        copy = PrototypeCopy()
        return FixedPromptTemplate(
            version=copy.template_version(),
            role=copy.role(),
            structure=copy.structure(),
            tone=copy.tone(),
            disclosure=copy.disclosure(),
        )


class TestFixedPromptTemplateContract(PromptTemplatePortContract):
    def port(self) -> PromptTemplatePort:
        return Template().build()


class TestFixedPromptTemplate:
    def test_the_template_encodes_role_context_proficiency_structure_and_tone(
        self,
    ) -> None:
        rendered = (
            Template()
            .build()
            .render(
                "explain greetings",
                Samples().retrieval(),
                Samples().history(),
            )
        )
        assert rendered.template_version == "tpl-1"
        for part in (
            "Role:",
            "Tone:",
            "Output structure:",
            "Disclosure:",
            "Target proficiency: A1",
            "greet-1: correct",
            "kb://greetings",
            "Hola means hello.",
            "Task: explain greetings",
        ):
            assert part in rendered.text

    def test_missing_history_is_said_to_be_not_on_record(self) -> None:
        history = (
            Samples()
            .history()
            .model_copy(update={"proficiency_level": None, "events": None})
        )
        rendered = Template().build().render("task", Samples().retrieval(), history)
        assert "Target proficiency: not on record" in rendered.text
        assert "Prior outcomes: not on record" in rendered.text

    def test_an_admitted_empty_event_list_is_not_silence(self) -> None:
        history = Samples().history().model_copy(update={"events": ()})
        rendered = (
            Template()
            .build()
            .render(
                "task",
                Samples()
                .retrieval()
                .model_copy(update={"snippets": (), "sources": ()}),
                history,
            )
        )
        assert "Prior outcomes: none admitted" in rendered.text
        assert "Retrieved context:\nnone" in rendered.text

    def test_an_incorrect_outcome_is_named(self) -> None:
        item = Samples().history_item().model_copy(update={"correct": False})
        history = Samples().history().model_copy(update={"events": (item,)})
        rendered = Template().build().render("task", Samples().retrieval(), history)
        assert "greet-1: incorrect" in rendered.text

    def test_an_empty_section_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="template version"):
            FixedPromptTemplate(
                version="  ",
                role="role",
                structure="structure",
                tone="tone",
                disclosure="disclosure",
            )


class TestScriptedLanguageModelContract(LanguageModelPortContract):
    def port(self) -> LanguageModelPort:
        return ScriptedLanguageModel("hola", "a" * 40, Samples().decoding())


class TestScriptedLanguageModel:
    def test_an_empty_revision_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="revision"):
            ScriptedLanguageModel("hola", "  ", Samples().decoding())


class TestModelRevision:
    def test_a_tag_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="not a tag"):
            ModelRevision("qwen3:8b")

    def test_a_sha_is_accepted(self) -> None:
        sha = "a" * 40
        assert ModelRevision(sha).value() == sha


class TestPinnedRevision:
    def test_the_runtime_file_matches_the_pin(self) -> None:
        path = Path(__file__).resolve().parents[3] / "config" / "runtime.toml"
        assert PinnedRevision(path).sha() == RuntimePin().weights_sha()

    def test_a_missing_model_table_is_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "runtime.toml"
        path.write_text("model = 'qwen'\n", encoding="utf-8")
        with pytest.raises(TypeError, match="model pin"):
            PinnedRevision(path).sha()

    def test_a_non_string_sha_is_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "runtime.toml"
        path.write_text("[model]\nweights_sha = 1\n", encoding="utf-8")
        with pytest.raises(TypeError, match="weights_sha"):
            PinnedRevision(path).sha()


_PIN = "a" * 64
_OTHER = "b" * 64


class Modelfile:
    """The ``FROM`` line Ollama writes for a model's weights blob."""

    def naming(self, digest: str) -> str:
        return f"# Modelfile\nFROM /root/.ollama/models/blobs/sha256-{digest}\n"


class ScriptedEndpoint(OllamaEndpoint):
    """Stand-in for the local runtime. Not an HTTP call.

    ``after`` is the weights the name reports once generation has run, so a
    repoint during generation can be simulated.
    """

    def __init__(
        self,
        weights: dict[str, str],
        text: str = "hola",
        after: dict[str, str] | None = None,
    ) -> None:
        self._weights = weights
        self._after = after
        self._text = text
        self.generated: list[str] = []

    def names(self) -> tuple[str, ...]:
        return tuple(self._weights)

    def weights(self, model_name: str) -> str:
        if self.generated and self._after is not None:
            return self._after[model_name]
        return self._weights[model_name]

    def generate(self, model_name: str, prompt: str, decoding: DecodingParams) -> str:
        self.generated.append(model_name)
        return self._text


class TestModelfileWeights:
    def test_the_from_line_names_the_weights_digest(self) -> None:
        assert ModelfileWeights().digest(Modelfile().naming(_PIN)) == _PIN

    def test_a_colon_form_digest_is_read_too(self) -> None:
        assert ModelfileWeights().digest(f"FROM sha256:{_PIN}") == _PIN

    def test_no_weights_blob_or_two_fail_closed(self) -> None:
        with pytest.raises(ValueError, match="exactly one weights blob"):
            ModelfileWeights().digest("FROM qwen3:8b\n")
        with pytest.raises(ValueError, match="exactly one weights blob"):
            ModelfileWeights().digest(
                Modelfile().naming(_PIN) + Modelfile().naming(_OTHER)
            )


class TestPinnedModelName:
    def test_one_weights_match_is_the_name(self) -> None:
        name = PinnedModelName().resolve(_PIN, (("local", _PIN), ("other", _OTHER)))
        assert name == "local"

    def test_a_manifest_digest_is_not_a_match(self) -> None:
        # /api/tags reports the manifest digest; only the weights blob counts.
        with pytest.raises(ValueError, match="not one local"):
            PinnedModelName().resolve(_PIN, (("local", _OTHER),))

    def test_zero_or_two_matches_fail_closed(self) -> None:
        with pytest.raises(ValueError, match="not one local"):
            PinnedModelName().resolve(_PIN, ())
        with pytest.raises(ValueError, match="not one local"):
            PinnedModelName().resolve(_PIN, (("one", _PIN), ("two", _PIN)))


class Pinned:
    def model(self, endpoint: OllamaEndpoint) -> OllamaLanguageModel:
        return OllamaLanguageModel(
            ModelRevision(_PIN),
            endpoint,
            Samples().decoding(),
            PinnedModelName(),
        )


class TestOllamaLanguageModel:
    async def test_complete_uses_the_weights_match_and_records_the_sha(self) -> None:
        endpoint = ScriptedEndpoint({"qwen3:8b": _PIN, "other": _OTHER})
        model = Pinned().model(endpoint)
        completion = await model.complete(Samples().rendered_prompt())
        assert completion.text == "hola"
        assert completion.model_revision == model.revision() == _PIN
        assert completion.decoding_params == Samples().decoding()
        assert endpoint.generated == ["qwen3:8b"]

    async def test_a_name_repointed_during_generation_fails_the_completion(
        self,
    ) -> None:
        endpoint = ScriptedEndpoint({"qwen3:8b": _PIN}, after={"qwen3:8b": _OTHER})
        with pytest.raises(ValueError, match="changed weights"):
            await Pinned().model(endpoint).complete(Samples().rendered_prompt())

    async def test_no_local_model_with_the_pinned_weights_fails_closed(self) -> None:
        endpoint = ScriptedEndpoint({"qwen3:8b": _OTHER})
        with pytest.raises(ValueError, match="not one local"):
            await Pinned().model(endpoint).complete(Samples().rendered_prompt())
        assert endpoint.generated == []


class OllamaHandler(BaseHTTPRequestHandler):
    """A tiny Ollama stand-in on localhost."""

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/api/tags":
            self._json({"unexpected": True}, 404)
            return
        body = getattr(self.server, "tags_body", {"models": []})
        self._json(body, 200)

    def do_POST(self) -> None:  # noqa: N802
        target = getattr(self.server, "redirect_to", None)
        if isinstance(target, str):
            self.send_response(302)
            self.send_header("Location", target)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", "0"))
        sent = json.loads(self.rfile.read(length).decode("utf-8"))
        self.server.requests.append((self.path, sent))  # type: ignore[attr-defined]
        if self.path == "/api/show":
            self._json(getattr(self.server, "show_body", {}), 200)
            return
        self._json(getattr(self.server, "generate_body", {"response": "hola"}), 200)

    def log_message(self, format: str, *args: object) -> None:
        return None

    def _json(self, body: object, status: int) -> None:
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


class LocalOllama:
    def __init__(self) -> None:
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), OllamaHandler)
        self._server.requests = []  # type: ignore[attr-defined]
        self._thread = Thread(target=self._server.serve_forever, daemon=True)

    def start(self, tags: object, generate: object, show: object = None) -> str:
        self._server.tags_body = tags  # type: ignore[attr-defined]
        self._server.generate_body = generate  # type: ignore[attr-defined]
        self._server.show_body = show if show is not None else {}  # type: ignore[attr-defined]
        self._thread.start()
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def stop(self) -> None:
        self._server.shutdown()
        self._thread.join(timeout=2)

    def requests(self) -> list[tuple[str, object]]:
        return self._server.requests  # type: ignore[attr-defined, no-any-return]


class Endpoint:
    def at(self, base: str) -> UrllibOllamaEndpoint:
        return UrllibOllamaEndpoint(base, ModelfileWeights())


class TestUrllibOllamaEndpoint:
    def test_names_show_and_generate_round_trip(self) -> None:
        server = LocalOllama()
        base = server.start(
            {"models": [{"name": "qwen3:8b", "digest": "manifest"}]},
            {"response": "hola"},
            {"modelfile": Modelfile().naming(_PIN)},
        )
        try:
            endpoint = Endpoint().at(base + "/")
            assert endpoint.names() == ("qwen3:8b",)
            assert endpoint.weights("qwen3:8b") == _PIN
            text = endpoint.generate("qwen3:8b", "prompt", Samples().decoding())
            assert text == "hola"
            show, generate = server.requests()
            assert show == ("/api/show", {"model": "qwen3:8b"})
            assert generate[0] == "/api/generate"
            assert isinstance(generate[1], dict)
            assert generate[1]["stream"] is False
        finally:
            server.stop()

    def test_a_bad_catalogue_raises(self) -> None:
        cases = (
            {"models": "nope"},
            {"models": ["nope"]},
            {"models": [{"name": 1}]},
            {},
        )
        for body in cases:
            server = LocalOllama()
            base = server.start(body, {"response": "hola"})
            try:
                with pytest.raises(ValueError):
                    Endpoint().at(base).names()
            finally:
                server.stop()

    def test_a_show_without_a_modelfile_raises(self) -> None:
        server = LocalOllama()
        base = server.start({"models": []}, {"response": "hola"}, {"license": "x"})
        try:
            with pytest.raises(ValueError, match="no modelfile"):
                Endpoint().at(base).weights("qwen3:8b")
        finally:
            server.stop()

    def test_a_completion_without_text_raises(self) -> None:
        server = LocalOllama()
        base = server.start({"models": []}, {"response": 1})
        try:
            with pytest.raises(ValueError, match="no response"):
                Endpoint().at(base).generate("m", "p", Samples().decoding())
        finally:
            server.stop()

    def test_a_non_object_body_raises(self) -> None:
        server = LocalOllama()
        base = server.start([], {"response": "hola"})
        try:
            with pytest.raises(ValueError, match="non-object"):
                Endpoint().at(base).names()
        finally:
            server.stop()

    def test_an_unreachable_runtime_raises(self) -> None:
        with pytest.raises(ValueError, match="not reachable"):
            Endpoint().at("http://127.0.0.1:1").names()

    def test_a_hosted_url_is_refused_before_any_request(self) -> None:
        for base in (
            "https://api.example.com",
            "http://192.168.1.10:11434",
            "http://user:secret@127.0.0.1:11434",
            "http://2130706433",
        ):
            with pytest.raises(ValueError, match="ollama"):
                Endpoint().at(base)

    def test_a_redirect_is_not_followed(self) -> None:
        server = LocalOllama()
        base = server.start({"models": []}, {"response": "hola"})
        server._server.redirect_to = "https://api.example.com/api/generate"  # type: ignore[attr-defined]
        try:
            with pytest.raises(ValueError, match="must not redirect"):
                Endpoint().at(base).generate(
                    "m", "a minor's history", Samples().decoding()
                )
        finally:
            server.stop()

    def test_a_proxy_in_the_environment_does_not_receive_the_prompt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runtime = LocalOllama()
        proxy = LocalOllama()
        base = runtime.start({"models": []}, {"response": "hola"})
        proxy_url = proxy.start({"models": []}, {"response": "intercepted"})
        for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
            monkeypatch.setenv(name, proxy_url)
        for name in ("NO_PROXY", "no_proxy"):
            monkeypatch.delenv(name, raising=False)
        try:
            text = (
                Endpoint()
                .at(base)
                .generate("m", "a minor's history", Samples().decoding())
            )
        finally:
            runtime.stop()
            proxy.stop()
        assert text == "hola"
        assert proxy.requests() == []
        assert [path for path, _ in runtime.requests()] == ["/api/generate"]


class TestLocalOllamaUrl:
    def test_loopback_names_and_addresses_are_accepted(self) -> None:
        assert LocalOllamaUrl("http://127.0.0.1:11434/").value() == (
            "http://127.0.0.1:11434"
        )
        assert (
            LocalOllamaUrl("http://LOCALHOST:11434").value() == "http://LOCALHOST:11434"
        )
        assert "[::1]" in LocalOllamaUrl("http://[::1]:11434").value()

    def test_a_non_http_url_and_a_url_without_a_host_are_refused(self) -> None:
        for base in ("ftp://127.0.0.1:11434", "http://"):
            with pytest.raises(ValueError, match="http\\(s\\) loopback"):
                LocalOllamaUrl(base)


class TestHistoryFieldSetting:
    def test_unset_is_refused_and_blank_is_the_empty_set(self) -> None:
        with pytest.raises(ValueError, match="HISTORY_FIELDS"):
            HistoryFieldSetting().parse(None)
        assert HistoryFieldSetting().parse("") == HistoryFieldSet(fields=())
        assert HistoryFieldSetting().parse(
            " proficiency_level, events ,"
        ) == HistoryFieldSet(fields=("proficiency_level", "events"))

    def test_an_unknown_field_is_refused(self) -> None:
        with pytest.raises(ValueError, match="fields"):
            HistoryFieldSetting().parse("proficiency_level,pseudonym")
