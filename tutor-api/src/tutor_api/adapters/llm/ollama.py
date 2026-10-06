"""Local Qwen3, addressed by the pinned SHA (DEC-0007)."""

import asyncio
import ipaddress
import json
import re
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path

from tutor_core.domain.models.safety import (
    DecodingParams,
    ModelCompletion,
    RenderedPrompt,
)
from tutor_core.domain.ports.language_model import LanguageModelPort


class ModelRevision:
    """A commit SHA. A tag, including one that contains a colon, is rejected."""

    _SHA = re.compile(r"\A[0-9a-f]{12,64}\Z")

    def __init__(self, sha: str) -> None:
        if self._SHA.fullmatch(sha) is None:
            msg = "model revision must be a commit SHA, not a tag"
            raise ValueError(msg)
        self._sha = sha

    def value(self) -> str:
        """The SHA written into the audit record."""
        return self._sha


class PinnedRevision:
    """The weights SHA in ``config/runtime.toml``. Not a tag."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def sha(self) -> str:
        """Read and validate the pinned weights SHA."""
        with self._path.open("rb") as handle:
            loaded = tomllib.load(handle)
        model = loaded.get("model")
        if not isinstance(model, dict):
            msg = "model pin must be a table"
            raise TypeError(msg)
        value = model.get("weights_sha")
        if not isinstance(value, str):
            msg = "weights_sha must be a string"
            raise TypeError(msg)
        return ModelRevision(value).value()


class OllamaEndpoint(ABC):
    """How one adapter reaches the local Ollama runtime.

    Not a DEC-0001 port. The capability the pipeline holds is
    ``LanguageModelPort``. This seam exists so the model adapter can be
    tested without a running runtime.
    """

    @abstractmethod
    def names(self) -> tuple[str, ...]:
        """Return the name of each local model."""
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    def weights(self, model_name: str) -> str:
        """Return the hex digest of the weights blob ``model_name`` loads."""
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    def generate(self, model_name: str, prompt: str, decoding: DecodingParams) -> str:
        """Return the completion text for ``model_name``."""
        raise NotImplementedError  # pragma: no cover


class ModelfileWeights:
    """Read the weights digest from the ``FROM`` line of a modelfile.

    ``/api/tags`` reports a *manifest* digest, which is not the weights.
    The modelfile names the weights blob by its own digest, which is what
    ``config/runtime.toml`` pins (DEC-0007).
    """

    _FROM = re.compile(r"^FROM\s+\S*sha256[-:]([0-9a-f]{64})\s*$", re.MULTILINE)

    def digest(self, modelfile: str) -> str:
        """The single weights digest. None, or two, fail closed."""
        found = self._FROM.findall(modelfile)
        if len(found) != 1:
            msg = "modelfile does not name exactly one weights blob"
            raise ValueError(msg)
        return str(found[0])


class PinnedModelName:
    """The local model whose weights blob is the pinned SHA.

    The name is whatever Ollama calls that model. Configuration never
    supplies a tag. Zero matches or two matches fail closed.
    """

    def resolve(self, revision: str, weights: tuple[tuple[str, str], ...]) -> str:
        """Return the single name whose weights digest is ``revision``."""
        matches = tuple(name for name, digest in weights if digest.startswith(revision))
        if len(matches) != 1:
            msg = "pinned model revision is not one local Ollama model"
            raise ValueError(msg)
        return matches[0]


class LocalOllamaUrl:
    """A loopback base URL for the local runtime (DEC-0007).

    The rendered prompt includes a minor's admitted history. A hosted URL
    would send that off the machine, so the host must be loopback:
    ``localhost``, ``127.0.0.0/8``, or ``::1``. A name that merely resolves
    to loopback is rejected — it can be pointed elsewhere later. Userinfo
    is rejected so the host cannot be hidden beside credentials.
    """

    def __init__(self, raw: str) -> None:
        self._value = self._accept(raw)

    def value(self) -> str:
        """The normalised base URL, with no trailing slash."""
        return self._value

    def _accept(self, raw: str) -> str:
        parsed = urllib.parse.urlsplit(raw.strip())
        host = parsed.hostname
        if parsed.scheme not in {"http", "https"} or host is None:
            msg = "ollama base URL must be an http(s) loopback address"
            raise ValueError(msg)
        if parsed.username is not None or parsed.password is not None:
            msg = "ollama base URL must not carry credentials"
            raise ValueError(msg)
        if not self._loopback(host):
            msg = "ollama base URL must stay on the local machine"
            raise ValueError(msg)
        return raw.strip().rstrip("/")

    def _loopback(self, host: str) -> bool:
        if host.lower() == "localhost":
            return True
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return False
        return address.is_loopback


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
        """Fail the turn. Do not follow ``newurl``."""
        message = "ollama must not redirect"
        raise ValueError(message)


class UrllibOllamaEndpoint(OllamaEndpoint):
    """The local Ollama HTTP API, via the standard library."""

    def __init__(self, base_url: str, modelfile: ModelfileWeights) -> None:
        self._base_url = LocalOllamaUrl(base_url).value()
        self._modelfile = modelfile
        self._opener = urllib.request.build_opener(RefuseRedirect())

    def names(self) -> tuple[str, ...]:
        """GET ``/api/tags`` and read each model's name."""
        payload = self._get("/api/tags")
        models = payload.get("models")
        if not isinstance(models, list):
            msg = "ollama /api/tags did not list models"
            raise ValueError(msg)
        found: list[str] = []
        for model in models:
            if not isinstance(model, dict):
                msg = "ollama model entry is not an object"
                raise ValueError(msg)
            name = model.get("name")
            if not isinstance(name, str):
                msg = "ollama model entry has no name"
                raise ValueError(msg)
            found.append(name)
        return tuple(found)

    def weights(self, model_name: str) -> str:
        """POST ``/api/show`` and read the weights digest from the modelfile."""
        payload = self._post("/api/show", {"model": model_name})
        modelfile = payload.get("modelfile")
        if not isinstance(modelfile, str):
            msg = "ollama /api/show returned no modelfile"
            raise ValueError(msg)
        return self._modelfile.digest(modelfile)

    def generate(self, model_name: str, prompt: str, decoding: DecodingParams) -> str:
        """POST ``/api/generate`` and return the response text."""
        body = {
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": decoding.temperature,
                "top_p": decoding.top_p,
                "num_predict": decoding.max_tokens,
            },
        }
        payload = self._post("/api/generate", body)
        text = payload.get("response")
        if not isinstance(text, str):
            msg = "ollama completion has no response text"
            raise ValueError(msg)
        return text

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
            with self._opener.open(request, timeout=120) as response:
                raw = response.read()
        except urllib.error.URLError as exc:
            msg = "ollama is not reachable"
            raise ValueError(msg) from exc
        loaded = json.loads(raw.decode("utf-8"))
        if not isinstance(loaded, dict):
            msg = "ollama returned a non-object"
            raise ValueError(msg)
        return loaded


class OllamaLanguageModel(LanguageModelPort):
    """Complete through Ollama. ``revision`` is the pinned SHA, never a tag.

    The HTTP client is the injected endpoint. This class holds no
    retriever. A prompt cannot make it fetch anything except the local
    completion for the pinned weights.
    """

    def __init__(
        self,
        revision: ModelRevision,
        endpoint: OllamaEndpoint,
        decoding: DecodingParams,
        names: PinnedModelName,
    ) -> None:
        self._revision = revision
        self._endpoint = endpoint
        self._decoding = decoding
        self._names = names

    async def complete(self, prompt: RenderedPrompt) -> ModelCompletion:
        """Generate from the local model whose weights are the pinned SHA.

        The name is resolved, generation runs, and the name's weights are
        read again. A name repointed to other weights in between fails the
        turn instead of recording a revision that did not produce the text.
        """
        model_name = await asyncio.to_thread(self._pinned_name)
        text = await asyncio.to_thread(
            self._endpoint.generate, model_name, prompt.text, self._decoding
        )
        after = await asyncio.to_thread(self._endpoint.weights, model_name)
        if not after.startswith(self._revision.value()):
            msg = "the pinned model name changed weights during generation"
            raise ValueError(msg)
        return ModelCompletion(
            text=text,
            model_revision=self.revision(),
            decoding_params=self._decoding,
        )

    def _pinned_name(self) -> str:
        weights = tuple(
            (name, self._endpoint.weights(name)) for name in self._endpoint.names()
        )
        return self._names.resolve(self._revision.value(), weights)

    def revision(self) -> str:
        """The pinned SHA. This does not contact Ollama."""
        return self._revision.value()
