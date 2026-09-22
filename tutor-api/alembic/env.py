"""Alembic environment. The engine is created here, not at import of the app."""

from logging.config import fileConfig

from alembic import context

from tutor_api.adapters.persistence.migration_environment import MigrationEnvironment

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

MigrationEnvironment().run()
