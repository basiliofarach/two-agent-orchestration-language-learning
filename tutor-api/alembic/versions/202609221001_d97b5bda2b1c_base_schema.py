"""Base schema, born under the encryption guard (BE-05, DEC-0012)."""

from tutor_api.adapters.persistence.migration_session import MigrationSession
from tutor_api.adapters.persistence.schema import BaseSchema

revision = "d97b5bda2b1c"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    session = MigrationSession()
    session.install_guard()
    session.execute(BaseSchema().statements())


def downgrade() -> None:
    session = MigrationSession()
    session.execute(BaseSchema().downgrade_statements())
    session.execute(
        (
            "DROP EVENT TRIGGER IF EXISTS dec0012_no_plaintext_columns",
            "DROP FUNCTION IF EXISTS dec0012_reject_plaintext_columns()",
            "DROP TABLE IF EXISTS protected_column_exemption",
            "DROP DOMAIN IF EXISTS ciphertext",
        )
    )
