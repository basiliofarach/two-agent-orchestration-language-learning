"""The pinned Postgres image exposes pgvector (DEC-0006)."""

from __future__ import annotations

import os

import psycopg
from testcontainers.postgres import PostgresContainer
from tests.support.repository import RepositoryPaths
from tests.support.runtime_pin import RuntimePin


class TestPostgresRuntime:
    def setup_method(self) -> None:
        os.environ["TESTCONTAINERS_RYUK_DISABLED"] = "true"

    def _psycopg_url(self, postgres: PostgresContainer) -> str:
        raw = postgres.get_connection_url()
        return raw.replace("postgresql+psycopg2://", "postgresql://").replace(
            "postgresql+psycopg://",
            "postgresql://",
        )

    def test_vector_extension_can_be_created(self) -> None:
        image = RuntimePin().postgres_image()
        with (
            PostgresContainer(image=image) as postgres,
            psycopg.connect(self._psycopg_url(postgres)) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cursor.execute(
                "SELECT extname FROM pg_extension WHERE extname = %s",
                ("vector",),
            )
            row = cursor.fetchone()
        assert row is not None
        assert row[0] == "vector"

    def test_compose_pins_the_same_image_digest(self) -> None:
        root = RepositoryPaths().root()
        compose = (root / "tutor-api" / "docker-compose.yml").read_text(
            encoding="utf-8"
        )
        digest = RuntimePin().postgres_image()
        assert digest in compose

    def test_init_script_creates_a_distinct_application_role(self) -> None:
        root = RepositoryPaths().root()
        init = (
            root / "tutor-api" / "docker" / "postgres" / "init" / "01-roles.sh"
        ).read_text(encoding="utf-8")
        assert "CREATE ROLE" in init
        assert "POSTGRES_APP_USER" in init
        compose = (root / "tutor-api" / "docker-compose.yml").read_text(
            encoding="utf-8"
        )
        example = (root / "tutor-api" / ".env.example").read_text(encoding="utf-8")
        assert "POSTGRES_USER: ${POSTGRES_USER}" in compose
        assert "POSTGRES_APP_USER: ${POSTGRES_APP_USER}" in compose
        assert "POSTGRES_USER=tutor_owner" in example
        assert "POSTGRES_APP_USER=tutor_app" in example
