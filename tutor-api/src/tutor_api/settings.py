"""Validated database configuration read by the composition root."""

from typing import Annotated

from fastapi import Depends
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


# A plain assignment is deliberate. FastAPI currently unwraps this transparent
# alias, but not a Python 3.12 `type` alias (TypeAliasType).
Settings = Annotated[
    ApplicationSettings,
    Depends(Provide(ApplicationSettings)),
]
