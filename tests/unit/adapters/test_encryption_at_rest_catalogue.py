"""Unit checks for the DEC-0012 schema installer and PostgreSQL settings."""

import inspect
from pathlib import Path

import pytest
from pydantic import ValidationError

from tutor_api.adapters.persistence.encryption_at_rest import (
    ColumnExemption,
    EncryptionAtRestSchema,
)


class TestColumnExemption:
    def test_requires_a_nonempty_reason_and_forbids_extra_data(self) -> None:
        with pytest.raises(ValidationError):
            ColumnExemption(table_name="learner", column_name="name", reason="")
        with pytest.raises(ValidationError):
            ColumnExemption(
                table_name="learner",
                column_name="name",
                reason="fixture",
                undeclared="not allowed",
            )

    def test_is_frozen(self) -> None:
        exemption = ColumnExemption(
            table_name="learner",
            column_name="name",
            reason="fixture",
        )
        with pytest.raises(ValidationError):
            exemption.reason = "changed"


class TestEncryptionAtRestSchema:
    def test_exposes_only_install_as_a_public_method(self) -> None:
        public = {
            name
            for name, member in inspect.getmembers(
                EncryptionAtRestSchema, predicate=inspect.isfunction
            )
            if not name.startswith("_")
        }
        assert public == {"install"}

    def test_schema_uses_no_database_side_cryptography(self) -> None:
        source = inspect.getsource(EncryptionAtRestSchema).lower()
        assert "create extension pgcrypto" not in source
        assert "pgp_sym_encrypt" not in source

    def test_compose_does_not_log_statements_or_bind_parameters(self) -> None:
        root = Path(__file__).resolve().parents[3]
        compose = (root / "tutor-api" / "docker-compose.yml").read_text(
            encoding="utf-8"
        )
        assert "log_statement=none" in compose
        assert "log_parameter_max_length=0" in compose
