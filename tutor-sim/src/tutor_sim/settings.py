"""Harness settings. The role-model URL stays on this machine."""

import ipaddress
from pathlib import Path
from urllib import parse

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LoopbackOllamaUrl:
    """A loopback base URL. A name that merely resolves to loopback is refused."""

    def __init__(self, raw: str) -> None:
        self._value = self._accept(raw)

    def value(self) -> str:
        """The base URL, with no trailing slash."""
        return self._value

    def _accept(self, raw: str) -> str:
        parsed = parse.urlsplit(raw.strip())
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


class SimulationSettings(BaseSettings):
    """Where the dataset, the cache, and the role model live."""

    model_config = SettingsConfigDict(env_prefix="SIM_", extra="ignore")

    api_base_url: str = "http://127.0.0.1:8000"
    dataset_dir: Path = Path("datasets/sim/unreleased")
    evidence_dir: Path = Path("evidence")
    ollama_base_url: str = "http://127.0.0.1:11434"
    runtime_pin_path: Path = Path("config/runtime.toml")
    seed: int = 0
    cache_dir: Path = Path(".cache/sim")
    offline: bool = False
    sources_path: Path = Path("datasets/sim/unreleased/public/sources.json")

    @field_validator("ollama_base_url")
    @classmethod
    def role_model_stays_local(cls, value: str) -> str:
        """Refuse a hosted runtime. The rendered prompt can carry history."""
        return LoopbackOllamaUrl(value).value()
