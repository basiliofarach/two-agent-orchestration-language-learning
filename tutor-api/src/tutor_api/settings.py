"""Settings read from the process environment and ``tutor-api/.env``.

Pydantic owns the reading and the precedence (DEC-0002): an exported variable
beats the file, which is what Compose already does and what lets CI supply a
URL without editing a checked-in file. Nothing is read at import — a settings
object is constructed by the composition root that needs it.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# The package lives at tutor-api/src/tutor_api/, so the file Compose reads is
# two levels up. An absolute path rather than a bare ".env": Alembic, pytest
# and the API are not all invoked from the same working directory.
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class DatabaseSettings(BaseSettings):
    """Where the database is and who connects to it.

    ``extra="ignore"`` rather than the ``extra="forbid"`` of an audit record
    (DEC-0002): the same ``.env`` carries values this class has no business
    modelling, and the process environment carries the whole shell. Forbidding
    here would fail on ``PATH``. The data-minimisation argument applies to what
    is written to the log, not to what configures a connection.
    """

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str | None = None
    postgres_user: str | None = None
    postgres_password: str | None = None
    postgres_db: str | None = None
    postgres_host: str = "127.0.0.1"
    postgres_port: str = "5432"
    postgres_app_user: str = "tutor_app"
