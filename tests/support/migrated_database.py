"""Upgrade a fresh database and seed the learner the audit row references."""

from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config

_LEARNER = "00000000-0000-4000-8000-000000000001"
_SESSION = "00000000-0000-4000-8000-000000000004"
_ENVELOPE = b"\x01" + bytes(44)


class PostgresUrl:
    """The driver flavours one database is reached by."""

    def __init__(self, plain: str) -> None:
        self._plain = plain

    def sync(self) -> str:
        return self._plain.replace("postgresql://", "postgresql+psycopg://", 1)

    def async_url(self) -> str:
        return self._plain.replace("postgresql://", "postgresql+asyncpg://", 1)


class MigratedDatabase:
    """``upgrade head``, then the learner and session an audit row needs."""

    def upgrade(self, url: str) -> None:
        root = Path(__file__).resolve().parents[2] / "tutor-api"
        config = Config(str(root / "alembic.ini"))
        config.set_main_option("script_location", str(root / "alembic"))
        config.set_main_option("sqlalchemy.url", PostgresUrl(url).sync())
        command.upgrade(config, "head")

    def seed_learner(self, url: str) -> None:
        with psycopg.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO learner (
                    learner_id, pseudonym, proficiency_level, retain_until
                ) VALUES (%s, %s, %s, '2026-12-01T00:00:00Z')
                """,
                (_LEARNER, _ENVELOPE, _ENVELOPE),
            )
            cursor.execute(
                """
                INSERT INTO tutoring_session (
                    id, tutor_id, learner_id, started_at
                ) VALUES (%s, %s, %s, '2026-01-01T00:00:00Z')
                """,
                (_SESSION, _ENVELOPE, _LEARNER),
            )
