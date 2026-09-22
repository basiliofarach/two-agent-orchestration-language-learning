"""Online Alembic run. Revision ids stay Alembic's hash (see ``alembic.ini``)."""

from alembic import context
from alembic.config import Config
from sqlalchemy import engine_from_config, pool

from tutor_api.adapters.persistence.database_url import MigrationDatabaseUrl


class MigrationEnvironment:
    """Connect and migrate on one short-lived engine."""

    def __init__(self, url: MigrationDatabaseUrl) -> None:
        self._url = url

    def run(self) -> None:
        """Apply the configured command on one short-lived engine."""
        config = context.config
        self.ensure_url(config)
        section = config.get_section(config.config_ini_section, {})
        connectable = engine_from_config(
            section,
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )
        with connectable.connect() as connection:
            context.configure(connection=connection, target_metadata=None)
            with context.begin_transaction():
                context.run_migrations()
        connectable.dispose()

    def ensure_url(self, config: Config) -> None:
        """Set the connection URL unless the caller already supplied one.

        A URL already on the config wins: the integration suite points Alembic
        at a testcontainer with ``set_main_option``, and resolving over the top
        of that would send migrations to the developer's own database. This
        runs before ``get_section``, which snapshots the values the engine is
        built from.
        """
        if not config.get_main_option("sqlalchemy.url", None):
            config.set_main_option("sqlalchemy.url", self._url.escaped())
