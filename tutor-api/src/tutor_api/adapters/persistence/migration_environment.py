"""Online Alembic run. Revision ids stay Alembic's hash (see ``alembic.ini``)."""

from alembic import context
from sqlalchemy import engine_from_config, pool


class MigrationEnvironment:
    """Connect and migrate on one short-lived engine."""

    def run(self) -> None:
        """Apply the configured command on one short-lived engine."""
        config = context.config
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
