"""The role model refuses the system's weights and stays on loopback."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from tests.support.runtime_pin import RuntimePin

from tutor_sim.adapters.role_model import (
    OllamaRoleModel,
    PosTaggerPin,
    RoleChat,
    RoleChatLimits,
    RoleModelfile,
    RoleModelPin,
    SameWeights,
    ScriptedRoleModel,
    TomlTable,
    UrllibRoleChat,
    WeightsDigest,
)
from tutor_sim.domain.ports.role_model import RoleModelPort

_ROLE = "b" * 64
_SYSTEM = "a" * 64
_OTHER = "c" * 64


class PinFile:
    def write(self, path: Path, table: str, fields: dict[str, str]) -> None:
        lines = [f"[{table}]"]
        lines.extend(f'{name} = "{value}"' for name, value in fields.items())
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class ScriptedHttp(BaseHTTPRequestHandler):
    mode = "ok"
    role = _ROLE
    tags_calls = 0
    last_chat: dict[str, object] = {}

    def do_GET(self) -> None:  # noqa: N802
        type(self).tags_calls += 1
        if self.mode == "redirect":
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1/away")
            self.end_headers()
            return
        if self.mode == "list":
            self._json([])
            return
        if self.mode == "no-list":
            self._json({"models": {}})
            return
        if self.mode == "bad-entry":
            self._json({"models": ["x"]})
            return
        if self.mode == "no-name":
            self._json({"models": [{}]})
            return
        if self.mode == "two":
            self._json({"models": [{"name": "one"}, {"name": "two"}]})
            return
        if self.mode == "none":
            self._json({"models": [{"name": "system"}]})
            return
        if self.mode == "mixed":
            self._json({"models": [{"name": "vision"}, {"name": "role"}]})
            return
        self._json({"models": [{"name": "role"}]})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/api/show":
            self._show(str(body.get("model")))
            return
        type(self).last_chat = body
        if self.mode == "slow":
            time.sleep(1.0)
        if self.mode == "no-message":
            self._json({})
            return
        if self.mode == "empty":
            self._json({"message": {"content": ""}})
            return
        if self.mode == "bad-message":
            self._json({"message": []})
            return
        self._json({"message": {"content": "hello"}})

    def _show(self, name: str) -> None:
        if self.mode == "no-modelfile":
            self._json({})
            return
        if self.mode == "two-from" or name == "vision":
            body = f"FROM sha256-{self.role}\nFROM sha256-{_OTHER}\n"
            self._json({"modelfile": body})
            return
        digest = _SYSTEM if self.mode == "none" else self.role
        self._json({"modelfile": f"FROM sha256-{digest}\n"})

    def _json(self, payload: object) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, fmt: str, *args: object) -> None:
        return


class LocalOllama:
    def __init__(self, mode: str) -> None:
        self._mode = mode
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def url(self) -> str:
        assert self._server is not None
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> "LocalOllama":
        ScriptedHttp.mode = self._mode
        ScriptedHttp.tags_calls = 0
        ScriptedHttp.last_chat = {}
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), ScriptedHttp)
        self._thread = threading.Thread(target=self._server.serve_forever)
        self._thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        assert self._server is not None
        assert self._thread is not None
        self._server.shutdown()
        self._thread.join()
        self._server.server_close()


class TestRoleModel:
    def test_equal_weights_are_refused(self, tmp_path: Path) -> None:
        with pytest.raises(SameWeights, match="system model"):
            OllamaRoleModel(
                _SYSTEM,
                _SYSTEM,
                UrllibRoleChat("http://127.0.0.1:9", RoleModelfile(), RoleChatLimits()),
            )
        with pytest.raises(ValueError, match="64 hex"):
            OllamaRoleModel(
                "latest",
                _SYSTEM,
                UrllibRoleChat("http://127.0.0.1:9", RoleModelfile(), RoleChatLimits()),
            )
        path = tmp_path / "runtime.toml"
        PinFile().write(path, "role_model", {"weights_sha": _SYSTEM})
        with pytest.raises(SameWeights):
            RoleModelPin(path, _SYSTEM).weights_sha()
        PinFile().write(path, "role_model", {"weights_sha": _ROLE})
        assert RoleModelPin(path, _SYSTEM).weights_sha() == _ROLE
        with pytest.raises(ValueError, match="64 hex"):
            RoleModelPin(path, "latest")

    def test_a_scripted_role_returns_its_utterance(self) -> None:
        role = ScriptedRoleModel(_ROLE, "I like music.")
        assert role.weights_sha() == _ROLE
        assert role.complete("You are a pupil.", "Ask for help.") == "I like music."
        with pytest.raises(ValueError, match="system prompt"):
            role.complete("", "Ask.")
        with pytest.raises(ValueError, match="user turn"):
            role.complete("You are a pupil.", "")
        with pytest.raises(ValueError, match="64 hex"):
            ScriptedRoleModel("tag", "no")
        incomplete = type("Incomplete", (RoleModelPort,), {})
        with pytest.raises(TypeError, match="abstract"):
            incomplete()
        chat = type("IncompleteChat", (RoleChat,), {})
        with pytest.raises(TypeError, match="abstract"):
            chat()

    def test_a_missing_pin_table_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "runtime.toml"
        path.write_text('[model]\nweights_sha = "' + _SYSTEM + '"\n', encoding="utf-8")
        with pytest.raises(TypeError, match="pos_tagger"):
            PosTaggerPin(path).version()
        PinFile().write(path, "pos_tagger", {"version": ""})
        with pytest.raises(TypeError, match="version"):
            TomlTable(path, "pos_tagger").field("version")
        path.write_text("[pos_tagger]\nversion = 1\n", encoding="utf-8")
        with pytest.raises(TypeError, match="version"):
            TomlTable(path, "pos_tagger").field("version")
        PinFile().write(
            path,
            "pos_tagger",
            {
                "binary_sha256": _ROLE,
                "parameter_file_sha256": _OTHER,
                "version": "3.2.5",
            },
        )
        pin = PosTaggerPin(path)
        assert pin.binary_sha256() == _ROLE
        assert pin.parameter_sha256() == _OTHER
        assert pin.version() == "3.2.5"
        PinFile().write(path, "pos_tagger", {"version": "latest"})
        with pytest.raises(ValueError, match="pinned"):
            PosTaggerPin(path).version()
        with pytest.raises(ValueError, match="one weights"):
            RoleModelfile().digest("FROM somewhere\n")
        assert RoleModelfile().digest(f"FROM sha256-{_ROLE}\n") == _ROLE
        assert WeightsDigest().parse(_ROLE) == _ROLE

    def test_the_loopback_chat_reads_one_matching_model(self) -> None:
        with LocalOllama("ok") as server:
            role = OllamaRoleModel(
                _ROLE,
                _SYSTEM,
                UrllibRoleChat(server.url(), RoleModelfile(), RoleChatLimits()),
            )
            assert role.weights_sha() == _ROLE
            assert role.complete("You are a pupil.", "Say hello.") == "hello"
        with pytest.raises(ValueError, match="local machine"):
            UrllibRoleChat(
                "http://example.com:11434", RoleModelfile(), RoleChatLimits()
            )

    @pytest.mark.parametrize(
        ("mode", "message"),
        [
            ("redirect", "redirect"),
            ("list", "non-object"),
            ("no-list", "did not list"),
            ("bad-entry", "not an object"),
            ("no-name", "no name"),
            ("two", "not one local"),
            ("none", "not one local"),
            ("no-modelfile", "no modelfile"),
            ("two-from", "not one local"),
            ("no-message", "no message"),
            ("empty", "no text"),
            ("bad-message", "no message"),
        ],
    )
    def test_a_bad_runtime_fails_closed(self, mode: str, message: str) -> None:
        with LocalOllama(mode) as server:
            chat = UrllibRoleChat(server.url(), RoleModelfile(), RoleChatLimits())
            with pytest.raises(ValueError, match=message):
                chat.chat(_ROLE, "system", "user")

    def test_the_chat_sends_the_configured_token_budget(self) -> None:
        with LocalOllama("ok") as server:
            limits = RoleChatLimits(max_tokens=700, timeout_seconds=5)
            chat = UrllibRoleChat(server.url(), RoleModelfile(), limits)
            assert chat.chat(_ROLE, "system", "user") == "hello"
        options = ScriptedHttp.last_chat["options"]
        assert isinstance(options, dict)
        assert options["num_predict"] == 700

    def test_the_default_budget_fits_a_verbatim_payload(self) -> None:
        # A HackAPrompt or BIPIA payload runs to hundreds of tokens; the
        # construction check needs it back verbatim, so 16 tokens cannot do.
        assert RoleChatLimits().max_tokens >= 512
        assert RoleChatLimits().timeout_seconds >= 60

    def test_a_slow_runtime_times_out_as_a_runtime_error(self) -> None:
        with LocalOllama("slow") as server:
            limits = RoleChatLimits(timeout_seconds=0.2)
            chat = UrllibRoleChat(server.url(), RoleModelfile(), limits)
            with pytest.raises(ValueError, match="timed out"):
                chat.chat(_ROLE, "system", "user")

    def test_the_digest_is_resolved_once_per_chat(self) -> None:
        with LocalOllama("ok") as server:
            chat = UrllibRoleChat(server.url(), RoleModelfile(), RoleChatLimits())
            chat.chat(_ROLE, "system", "user")
            chat.chat(_ROLE, "system", "again")
        assert ScriptedHttp.tags_calls == 1

    def test_another_model_with_two_blobs_does_not_block_the_role(self) -> None:
        with LocalOllama("mixed") as server:
            chat = UrllibRoleChat(server.url(), RoleModelfile(), RoleChatLimits())
            assert chat.chat(_ROLE, "system", "user") == "hello"

    def test_limits_reject_a_zero_budget(self) -> None:
        with pytest.raises(ValueError, match="greater than"):
            RoleChatLimits(max_tokens=0)
        with pytest.raises(ValueError, match="greater than"):
            RoleChatLimits(timeout_seconds=0)
        with pytest.raises(ValueError, match="Extra inputs"):
            RoleChatLimits.model_validate({"stream": True})

    def test_an_unreachable_runtime_fails_closed(self) -> None:
        chat = UrllibRoleChat("http://127.0.0.1:9", RoleModelfile(), RoleChatLimits())
        with pytest.raises(ValueError, match="not reachable"):
            chat.chat(_ROLE, "system", "user")

    @pytest.mark.requires_ollama
    def test_a_live_runtime_is_used_only_for_a_different_model(self) -> None:
        from tests.integration.test_ollama_revision import OllamaRuntime

        if not OllamaRuntime().is_reachable():
            pytest.skip("Ollama is not running on localhost:11434")
        system = RuntimePin().weights_sha()
        with pytest.raises(SameWeights):
            OllamaRoleModel(
                system,
                system,
                UrllibRoleChat(
                    "http://127.0.0.1:11434", RoleModelfile(), RoleChatLimits()
                ),
            )
        role = self._other(system)
        if role is None:
            pytest.skip("no role model distinct from the system model is installed")
        chat = UrllibRoleChat(
            "http://127.0.0.1:11434", RoleModelfile(), RoleChatLimits()
        )
        text = OllamaRoleModel(role, system, chat).complete(
            "Reply in one word.", "Say yes."
        )
        assert text.strip()

    def _other(self, system: str) -> str | None:
        from tests.integration.test_ollama_revision import OllamaRuntime

        body = OllamaRuntime().tags_body()
        models = body.get("models", [])
        if not isinstance(models, list):
            return None
        chat = UrllibRoleChat(
            "http://127.0.0.1:11434", RoleModelfile(), RoleChatLimits()
        )
        for model in models:
            if not isinstance(model, dict) or not isinstance(model.get("name"), str):
                continue
            try:
                digest = chat._weights(model["name"])
            except ValueError:
                continue
            if digest != system:
                return digest
        return None
