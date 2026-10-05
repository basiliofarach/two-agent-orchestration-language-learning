"""Validated database configuration read by the composition root."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from tutor_api.di.dependency import Provide


class ApplicationSettings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str | None = None
    postgres_user: str | None = None
    postgres_password: str | None = None
    postgres_db: str | None = None
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    postgres_app_user: str = "tutor_app"
    postgres_app_password: str | None = None
    # The application's own URL, as the application role. Alembic's
    # DATABASE_URL is the owner's and is never used to serve a request.
    application_database_url: str | None = None
    # The KEK is injected from the environment, never a constant (DEC-0012).
    # Base64 of 32 bytes; the id is written into every envelope header.
    tutor_kek: SecretStr | None = None
    tutor_kek_id: UUID | None = None


# A plain assignment is deliberate. FastAPI currently unwraps this transparent
# alias, but not a Python 3.12 `type` alias (TypeAliasType).
Settings = Annotated[
    ApplicationSettings,
    Depends(Provide(ApplicationSettings)),
]
