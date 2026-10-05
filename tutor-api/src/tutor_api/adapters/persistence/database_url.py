"""Build the URLs Alembic and the application connect with. Nothing is read here."""

from urllib.parse import quote, urlsplit

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
        return DriverSwap(self.SYNC_DRIVER).apply(url)


class DriverSwap:
    """Replace a recognised Postgres driver prefix. Others pass through."""

    _INTERCHANGEABLE = (
        "postgresql+asyncpg",
        "postgresql+psycopg2",
        "postgresql+psycopg",
        "postgresql",
        "postgres",
    )

    def __init__(self, driver: str) -> None:
        self._driver = driver

    def apply(self, url: str) -> str:
        """Return ``url`` with its driver replaced by this one."""
        for driver in self._INTERCHANGEABLE:
            prefix = f"{driver}://"
            if url.startswith(prefix):
                return f"{self._driver}://{url[len(prefix) :]}"
        return url


class UrlUser:
    """The login name in a Postgres URL. Absent means the URL names none."""

    def __init__(self, url: str, variable: str = "APPLICATION_DATABASE_URL") -> None:
        self._url = url
        self._variable = variable

    def value(self) -> str:
        """Return the decoded user. Raise when the URL has none."""
        username = urlsplit(self._url).username
        if not username:
            msg = f"{self._variable} has no user"
            raise ValueError(msg)
        return username


class MigrationOwner:
    """The role Alembic connects as, from the source that URL is built from.

    ``DATABASE_URL`` wins, as it does in :class:`MigrationDatabaseUrl`, so
    its user is the owner even when ``POSTGRES_USER`` names someone else.
    """

    def __init__(self, settings: ApplicationSettings) -> None:
        self._settings = settings

    def name(self) -> str:
        """Return the owner's login. Raise when neither source names one."""
        configured = self._settings.database_url
        if configured:
            return UrlUser(configured, "DATABASE_URL").value()
        if self._settings.postgres_user:
            return self._settings.postgres_user
        msg = (
            "cannot tell the migration owner from the application role: "
            "set POSTGRES_USER or DATABASE_URL"
        )
        raise ValueError(msg)


class ApplicationRoleUrl:
    """An application URL that logs in as the application role (DEC-0014)."""

    def __init__(self, role: str) -> None:
        self._role = role

    def require(self, url: str) -> str:
        """Return ``url`` when its user is this role. Reject any other login."""
        username = UrlUser(url).value()
        if username != self._role:
            msg = (
                "APPLICATION_DATABASE_URL connects as "
                f"{username!r}, not the application role {self._role!r}"
            )
            raise ValueError(msg)
        return url


class DistinctFromOwner:
    """The application role is never the migration owner (DEC-0014)."""

    def __init__(self, owner: str) -> None:
        self._owner = owner

    def require(self, role: str) -> str:
        """Return ``role`` when it is not the owner. Reject it otherwise."""
        if role == self._owner:
            msg = (
                f"POSTGRES_APP_USER {role!r} is the migration owner; "
                "the application must connect as its own role"
            )
            raise ValueError(msg)
        return role


class ApplicationDatabaseUrl:
    """The async URL the application serves requests with (DEC-0014).

    The application role, not the owner: ``tutor_app`` holds only the grants
    the request path needs, so a request cannot alter the schema.
    ``APPLICATION_DATABASE_URL`` is accepted only when its user is
    ``postgres_app_user``. An override that logs in as the migration owner
    is rejected, and so is a ``postgres_app_user`` equal to the owner, which
    would pass that check. The owner is read from ``DATABASE_URL`` or
    ``POSTGRES_USER``, as Alembic reads it; when neither names one, the URL
    is refused rather than assumed to differ. Otherwise the URL is
    composed from ``POSTGRES_APP_*`` and the shared host, port and database.
    """

    ASYNC_DRIVER = "postgresql+asyncpg"

    def __init__(self, settings: ApplicationSettings) -> None:
        self._settings = settings

    def value(self) -> str:
        """Return the URL, driver normalised to asyncpg."""
        role = DistinctFromOwner(MigrationOwner(self._settings).name()).require(
            self._settings.postgres_app_user
        )
        configured = self._settings.application_database_url
        if configured:
            normalised = DriverSwap(self.ASYNC_DRIVER).apply(configured)
            return ApplicationRoleUrl(role).require(normalised)
        password = self._required(
            "POSTGRES_APP_PASSWORD", self._settings.postgres_app_password
        )
        database = self._required("POSTGRES_DB", self._settings.postgres_db)
        return (
            f"{self.ASYNC_DRIVER}://"
            f"{quote(role, safe='')}:"
            f"{quote(password, safe='')}"
            f"@{self._settings.postgres_host}:{self._settings.postgres_port}"
            f"/{database}"
        )

    def _required(self, name: str, value: str | None) -> str:
        if not value:
            msg = f"{name} is not set. Export it or set APPLICATION_DATABASE_URL."
            raise ValueError(msg)
        return value
