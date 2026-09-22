"""Append-only audit tables (BE-06, DEC-0006)."""

from tutor_api.adapters.persistence.migration_session import MigrationSession
from tutor_api.adapters.persistence.schema import AuditSchema

revision = "46c99fd72506"
down_revision = "d97b5bda2b1c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    MigrationSession().execute(AuditSchema().statements())


def downgrade() -> None:
    MigrationSession().execute(AuditSchema().downgrade_statements())
