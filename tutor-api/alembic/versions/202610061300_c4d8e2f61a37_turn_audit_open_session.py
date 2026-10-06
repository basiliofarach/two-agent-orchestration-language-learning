"""Refuse a turn row in a stopped session, at the insert (ARCHITECTURE §8).

The request path checks the session before retrieval. This trigger checks
again when the turn row is inserted, under a share lock on the session, so
a stop committed while the model ran still leaves the session with no row.
"""

from tutor_api.adapters.persistence.migration_session import MigrationSession
from tutor_api.adapters.persistence.schema import TurnAuditOpenSession

revision = "c4d8e2f61a37"
down_revision = "e5b9c1a04f77"
branch_labels = None
depends_on = None


def upgrade() -> None:
    MigrationSession().execute(TurnAuditOpenSession().statements())


def downgrade() -> None:
    MigrationSession().execute(TurnAuditOpenSession().downgrade_statements())
