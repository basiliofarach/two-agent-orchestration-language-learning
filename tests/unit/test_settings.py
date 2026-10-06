"""Application settings are ordinary mutable configuration."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from tutor_api.settings import ApplicationSettings


class TestApplicationSettings:
    def test_reads_environment_fields(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text(
            "POSTGRES_PORT=5433\nPOSTGRES_PASSWORD=not-logged\n",
            encoding="utf-8",
        )
        settings = ApplicationSettings(_env_file=env_file)
        assert settings.postgres_port == 5433
        assert settings.postgres_password == "not-logged"

    def test_rejects_a_non_numeric_port(self) -> None:
        with pytest.raises(ValidationError):
            ApplicationSettings(_env_file=None, postgres_port="not-a-port")

    def test_a_hosted_ollama_url_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="local machine"):
            ApplicationSettings(
                _env_file=None,  # type: ignore[call-arg]
                ollama_base_url="https://api.example.com/v1",
            )

    def test_loopback_ollama_urls_are_accepted(self) -> None:
        for base in (
            "http://127.0.0.1:11434",
            "http://localhost:11434/",
            "http://[::1]:11434",
        ):
            settings = ApplicationSettings(
                _env_file=None,  # type: ignore[call-arg]
                ollama_base_url=base,
            )
            assert settings.ollama_base_url.rstrip("/") == base.rstrip("/")

    def test_is_mutable_configuration(self) -> None:
        settings = ApplicationSettings(_env_file=None)
        settings.postgres_port = 5433
        assert settings.postgres_port == 5433
