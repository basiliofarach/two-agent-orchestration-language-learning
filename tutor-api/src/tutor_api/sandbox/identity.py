"""The sandbox server, and the operator server it must not be."""

from pydantic import BaseModel, ConfigDict


class SandboxIdentity(BaseModel):
    """Coordinates of the throwaway database (BAS-46).

    The operator database is compose project ``tutor``, volume
    ``postgres-data``, on ``127.0.0.1`` port 5433 (5432 is the image default
    the operator file deliberately does not publish). This identity matches
    none of those, and ``docker-compose.sandbox.yml`` spells the same values
    with no ``${...}`` taken from ``tutor-api/.env``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    project: str = "tutor-sandbox"
    volume: str = "sandbox-data"
    host: str = "127.0.0.1"
    port: int = 55433
    database: str = "sandbox"
    user: str = "sandbox_owner"
    password: str = "sandbox_owner"
    app_user: str = "sandbox_app"
    app_password: str = "sandbox_app"

    def separated_from_the_operator(self) -> bool:
        """True when this server cannot be the one ``make up`` serves."""
        operator_ports = (5432, 5433)
        return (
            self.project != "tutor"
            and self.volume != "postgres-data"
            and self.host == "127.0.0.1"
            and self.port not in operator_ports
        )

    def maintenance_url(self) -> str:
        """psycopg URL of the sandbox server's own database."""
        return (
            f"postgresql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}"
        )

    def alembic_url(self) -> str:
        """The same server, with the synchronous driver Alembic imports."""
        return (
            f"postgresql+psycopg://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}"
        )

    def application_url(self) -> str:
        """The same server, with the async driver the application imports."""
        return (
            f"postgresql+asyncpg://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}"
        )

    def required_in_compose(self) -> tuple[str, ...]:
        """Lines the sandbox compose file must contain, spelled as here."""
        return (
            f"name: {self.project}",
            f"127.0.0.1:{self.port}:5432",
            f"{self.volume}:/var/lib/postgresql/data",
            f"POSTGRES_USER: {self.user}",
            f"POSTGRES_PASSWORD: {self.password}",
            f"POSTGRES_DB: {self.database}",
            f"POSTGRES_APP_USER: {self.app_user}",
            f"POSTGRES_APP_PASSWORD: {self.app_password}",
            "log_statement=none",
            "log_parameter_max_length=0",
        )

    def forbidden_in_compose(self) -> tuple[str, ...]:
        """Spellings that would attach this file to the operator database."""
        return (
            "postgres-data:",
            "${POSTGRES_",
            "container_name:",
            "127.0.0.1:5433:",
            "name: tutor\n",
        )
