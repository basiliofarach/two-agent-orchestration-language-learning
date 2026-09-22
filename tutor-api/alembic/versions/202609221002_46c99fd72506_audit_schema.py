"""Append-only audit tables (BE-06, DEC-0006)."""

from tutor_api.adapters.persistence.migration_session import MigrationSession
from tutor_api.adapters.persistence.schema import ApplicationRole, AuditSchema
from tutor_api.settings import DatabaseSettings

revision = "46c99fd72506"
down_revision = "d97b5bda2b1c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    schema = AuditSchema(ApplicationRole(DatabaseSettings().postgres_app_user))
    MigrationSession().execute(schema.statements())


def downgrade() -> None:
    schema = AuditSchema(ApplicationRole(DatabaseSettings().postgres_app_user))
    MigrationSession().execute(schema.downgrade_statements())
