"""Persona completions. The role model is not the system model (DEC-0015)."""

import json
import re
import tomllib
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path
from typing import cast

from pydantic import BaseModel, ConfigDict, Field

from tutor_sim.domain.ports.role_model import RoleModelPort
from tutor_sim.settings import LoopbackOllamaUrl


class SameWeights(ValueError):
    """The role model and the system model are the same weights blob."""


class UnreadableModelfile(ValueError):
    """A modelfile does not name exactly one weights blob."""


class RoleChatLimits(BaseModel):
    """How long a role completion may run, and how many tokens it may emit.

    A persona copies a payload verbatim, and a HackAPrompt or BIPIA payload
    runs to hundreds of tokens; a short cap truncates it and the
    construction check discards the case. The first completion also loads
    the weights, which takes tens of seconds on a laptop.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_tokens: int = Field(default=1024, gt=0)
    timeout_seconds: float = Field(default=300.0, gt=0)


class WeightsDigest:
    """A 64-character hex digest. A tag is refused."""

    _SHA = re.compile(r"\A[0-9a-f]{64}\Z")

    def parse(self, raw: str) -> str:
        """Return ``raw`` when it is 64 hex characters."""
        if self._SHA.fullmatch(raw) is None:
            msg = "weights digest must be 64 hex characters"
            raise ValueError(msg)
        return raw


class TomlTable:
    """One table in a TOML pin file."""

    def __init__(self, path: Path, table: str) -> None:
        self._path = path
        self._table = table

    def field(self, name: str) -> str:
        """The string stored at ``table.name``. Missing or empty is refused."""
        with self._path.open("rb") as handle:
            loaded = tomllib.load(handle)
        section = loaded.get(self._table)
        if not isinstance(section, dict):
            msg = f"{self._table} pin must be a table"
            raise TypeError(msg)
        value = section.get(name)
        if not isinstance(value, str) or not value:
            msg = f"{name} must be a string"
            raise TypeError(msg)
        return value


class RoleModelPin:
    """The ``[role_model]`` digest. It must differ from the system digest."""

    def __init__(self, path: Path, system_sha: str) -> None:
        self._table = TomlTable(path, "role_model")
        self._system = WeightsDigest().parse(system_sha)

    def weights_sha(self) -> str:
        """The role digest. Equality with the system digest is refused."""
        digest = WeightsDigest().parse(self._table.field("weights_sha"))
        if digest == self._system:
            msg = "the role model must not be the system model"
            raise SameWeights(msg)
        return digest


class PosTaggerPin:
    """The ``[pos_tagger]`` pin. Digests are hex. The version is not ``latest``."""

    def __init__(self, path: Path) -> None:
        self._table = TomlTable(path, "pos_tagger")

    def binary_sha256(self) -> str:
        """The TreeTagger binary digest."""
        return WeightsDigest().parse(self._table.field("binary_sha256"))

    def parameter_sha256(self) -> str:
        """The English parameter-file digest."""
        return WeightsDigest().parse(self._table.field("parameter_file_sha256"))

    def version(self) -> str:
        """The pinned TreeTagger version."""
        value = self._table.field("version")
        if value == "latest":
            msg = "tagger revision must be pinned"
            raise ValueError(msg)
        return value


class RoleTurn:
    """A completion needs both halves of the prompt."""

    def require(self, system: str, user: str) -> None:
        """Refuse a blank system prompt or a blank user turn."""
        if not system:
            msg = "a role completion needs a system prompt"
            raise ValueError(msg)
        if not user:
            msg = "a role completion needs a user turn"
            raise ValueError(msg)


class ScriptedRoleModel(RoleModelPort):
    """A fixed utterance. Tests use this so a role cannot call the network."""

    def __init__(self, sha: str, utterance: str) -> None:
        self._sha = WeightsDigest().parse(sha)
        self._utterance = utterance
        self._turn = RoleTurn()

    def weights_sha(self) -> str:
        """The digest recorded on the stimulus. It is not looked up."""
        return self._sha

    def complete(self, system: str, user: str) -> str:
        """Return the scripted utterance after the prompt is checked."""
        self._turn.require(system, user)
        return self._utterance


class EchoRoleModel(RoleModelPort):
    """Copy the user turn. The role-model weights are not chosen (DEC-0015).

    Realise plants the payload in the user turn, so the copy contains it
    and the construction check can see those bytes. This is not a stand-in
    digest for a model that has not been selected.
    """

    WEIGHTS_SHA = "c0" * 32

    def __init__(self, sha: str = WEIGHTS_SHA) -> None:
        self._sha = WeightsDigest().parse(sha)
        self._turn = RoleTurn()

    def weights_sha(self) -> str:
        """The digest recorded on the stimulus. It names no model blob."""
        return self._sha

    def complete(self, system: str, user: str) -> str:
        """Return the user turn after the prompt is checked."""
        self._turn.require(system, user)
        return user


class RoleChat(ABC):
    """How ``OllamaRoleModel`` reaches a runtime. Not a DEC-0001 port."""

    @abstractmethod
    def chat(self, weights_sha: str, system: str, user: str) -> str:
        """Complete once for the weights named by ``weights_sha``."""
        raise NotImplementedError  # pragma: no cover


class OllamaRoleModel(RoleModelPort):
    """Complete on the local role model. The system digest is refused."""

    def __init__(self, role_sha: str, system_sha: str, chat: RoleChat) -> None:
        digest = WeightsDigest()
        role = digest.parse(role_sha)
        system = digest.parse(system_sha)
        if role == system:
            msg = "the role model must not be the system model"
            raise SameWeights(msg)
        self._sha = role
        self._chat = chat
        self._turn = RoleTurn()

    def weights_sha(self) -> str:
        """The role digest this completion is drawn from."""
        return self._sha

    def complete(self, system: str, user: str) -> str:
        """Ask the injected chat for one utterance."""
        self._turn.require(system, user)
        return self._chat.chat(self._sha, system, user)


class RoleModelfile:
    """Read the weights digest from a modelfile ``FROM`` line."""

    _FROM = re.compile(r"^FROM\s+\S*sha256[-:]([0-9a-f]{64})\s*$", re.MULTILINE)

    def digest(self, modelfile: str) -> str:
        """The single weights digest. None, or two, fail closed."""
        found = self._FROM.findall(modelfile)
        if len(found) != 1:
            msg = "modelfile does not name exactly one weights blob"
            raise UnreadableModelfile(msg)
        return cast(str, found[0])


class RefuseRedirect(urllib.request.HTTPRedirectHandler):
    """A local runtime that redirects would send the prompt to the new host."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> urllib.request.Request | None:
        """Fail the completion. Do not follow ``newurl``."""
        message = "ollama must not redirect"
        raise ValueError(message)


class UrllibRoleChat(RoleChat):
    """Ollama ``/api/chat`` on a loopback URL, with an empty proxy table."""

    def __init__(
        self, base_url: str, modelfile: RoleModelfile, limits: RoleChatLimits
    ) -> None:
        self._base_url = LoopbackOllamaUrl(base_url).value()
        self._modelfile = modelfile
        self._limits = limits
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            RefuseRedirect(),
        )
        self._turn = RoleTurn()
        self._names: dict[str, str] = {}

    def chat(self, weights_sha: str, system: str, user: str) -> str:
        """Resolve the digest to one local name, then read the chat text."""
        self._turn.require(system, user)
        name = self._name(weights_sha)
        payload = self._post(
            "/api/chat",
            {
                "model": name,
                "stream": False,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "options": {
                    "temperature": 0,
                    "seed": 0,
                    "num_predict": self._limits.max_tokens,
                },
            },
        )
        message = payload.get("message")
        if not isinstance(message, dict):
            msg = "ollama chat returned no message"
            raise ValueError(msg)
        content = message.get("content")
        if not isinstance(content, str) or not content:
            msg = "ollama chat returned no text"
            raise ValueError(msg)
        return content

    def _name(self, weights_sha: str) -> str:
        """Resolve once per chat object. The digest, not the name, is pinned."""
        known = self._names.get(weights_sha)
        if known is not None:
            return known
        resolved = self._resolve(weights_sha)
        self._names[weights_sha] = resolved
        return resolved

    def _resolve(self, weights_sha: str) -> str:
        payload = self._get("/api/tags")
        models = payload.get("models")
        if not isinstance(models, list):
            msg = "ollama /api/tags did not list models"
            raise ValueError(msg)
        matches: list[str] = []
        for model in models:
            name = self._model_name(model)
            try:
                weights = self._weights(name)
            except UnreadableModelfile:
                # A vision model names a projector blob too. It cannot be the
                # pinned role model, so it does not block the lookup.
                continue
            if weights == weights_sha:
                matches.append(name)
        if len(matches) != 1:
            msg = "pinned role-model digest is not one local model"
            raise ValueError(msg)
        return matches[0]

    def _model_name(self, model: object) -> str:
        if not isinstance(model, dict):
            msg = "ollama model entry is not an object"
            raise ValueError(msg)
        name = model.get("name")
        if not isinstance(name, str):
            msg = "ollama model entry has no name"
            raise ValueError(msg)
        return name

    def _weights(self, name: str) -> str:
        shown = self._post("/api/show", {"model": name})
        modelfile = shown.get("modelfile")
        if not isinstance(modelfile, str):
            msg = "ollama /api/show returned no modelfile"
            raise ValueError(msg)
        return self._modelfile.digest(modelfile)

    def _get(self, path: str) -> dict[str, object]:
        request = urllib.request.Request(self._base_url + path, method="GET")
        return self._read(request)

    def _post(self, path: str, body: dict[str, object]) -> dict[str, object]:
        encoded = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self._base_url + path,
            data=encoded,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        return self._read(request)

    def _read(self, request: urllib.request.Request) -> dict[str, object]:
        try:
            with self._opener.open(
                request, timeout=self._limits.timeout_seconds
            ) as response:
                raw = response.read()
        except TimeoutError as exc:
            msg = f"ollama timed out after {self._limits.timeout_seconds}s"
            raise ValueError(msg) from exc
        except urllib.error.URLError as exc:
            msg = "ollama is not reachable"
            raise ValueError(msg) from exc
        loaded = json.loads(raw.decode("utf-8"))
        if not isinstance(loaded, dict):
            msg = "ollama returned a non-object"
            raise ValueError(msg)
        return loaded
