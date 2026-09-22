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

    def test_is_mutable_configuration(self) -> None:
        settings = ApplicationSettings(_env_file=None)
        settings.postgres_port = 5433
        assert settings.postgres_port == 5433
