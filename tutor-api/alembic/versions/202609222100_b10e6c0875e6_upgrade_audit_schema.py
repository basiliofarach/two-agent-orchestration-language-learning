"""Bring an already-stamped audit catalogue up to the current shape (BE-06)."""

from tutor_api.adapters.persistence.migration_session import MigrationSession
from tutor_api.adapters.persistence.schema import ApplicationRole, AuditSchemaUpgrade
from tutor_api.settings import ApplicationSettings

revision = "b10e6c0875e6"
down_revision = "46c99fd72506"
branch_labels = None
depends_on = None


def upgrade() -> None:
    role = ApplicationRole(ApplicationSettings().postgres_app_user)
    MigrationSession().execute(AuditSchemaUpgrade(role).statements())


def downgrade() -> None:
    role = ApplicationRole(ApplicationSettings().postgres_app_user)
    MigrationSession().execute(AuditSchemaUpgrade(role).downgrade_statements())
