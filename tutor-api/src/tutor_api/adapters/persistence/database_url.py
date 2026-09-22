"""Build the URL Alembic connects with from settings. Nothing is read here."""

from urllib.parse import quote

from tutor_api.settings import ApplicationSettings


class MigrationDatabaseUrl:
    """The synchronous URL Alembic connects with.

    ``DATABASE_URL`` wins outright; otherwise the URL is composed from the
    ``POSTGRES_*`` parts. Reading and precedence belong to
    :class:`~tutor_api.settings.ApplicationSettings`, so an exported variable
    beats ``tutor-api/.env`` without this class knowing how either is loaded.

    No credentials live in ``alembic.ini``. A URL committed there drifts from
    the roles ``docker/postgres/init`` provisions, and it is the wrong place
    for a password.

    The driver is normalised to psycopg because Alembic runs synchronously:
    the asyncpg URL the application itself uses raises ``MissingGreenlet``
    rather than connecting, and that failure does not name its cause.
    """

    SYNC_DRIVER = "postgresql+psycopg"

    _INTERCHANGEABLE = (
        "postgresql+asyncpg",
        "postgresql+psycopg2",
        "postgresql+psycopg",
        "postgresql",
        "postgres",
    )

    def __init__(self, settings: ApplicationSettings) -> None:
        self._settings = settings

    def value(self) -> str:
        """Return the URL, driver normalised for a synchronous connection."""
        configured = self._settings.database_url
        return self._with_sync_driver(configured or self._from_parts())

    def escaped(self) -> str:
        """The URL with ``%`` doubled, for Alembic's ConfigParser.

        ``set_main_option`` feeds ConfigParser, which reads ``%`` as the start
        of an interpolation. A percent-encoded password would otherwise raise
        on substitution instead of connecting.
        """
        return self.value().replace("%", "%%")

    def _from_parts(self) -> str:
        user = self._required("POSTGRES_USER", self._settings.postgres_user)
        password = self._required("POSTGRES_PASSWORD", self._settings.postgres_password)
        database = self._required("POSTGRES_DB", self._settings.postgres_db)
        # The credentials are percent-encoded: a password containing @, : or /
        # would otherwise be read as the host, the port or the database name.
        return (
            f"{self.SYNC_DRIVER}://{quote(user, safe='')}:"
            f"{quote(password, safe='')}"
            f"@{self._settings.postgres_host}:{self._settings.postgres_port}"
            f"/{database}"
        )

    def _required(self, name: str, value: str | None) -> str:
        if not value:
            msg = (
                f"{name} is not set. Export it, set DATABASE_URL, or copy "
                "tutor-api/.env.example to tutor-api/.env."
            )
            raise ValueError(msg)
        return value

    def _with_sync_driver(self, url: str) -> str:
        for driver in self._INTERCHANGEABLE:
            prefix = f"{driver}://"
            if url.startswith(prefix):
                return f"{self.SYNC_DRIVER}://{url[len(prefix) :]}"
        return url
