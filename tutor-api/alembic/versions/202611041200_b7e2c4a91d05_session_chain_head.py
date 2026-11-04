"""Anchor each session's turn-chain head outside the turn rows.

A deleted tail still links from the genesis hash. The head stored on the
session is what makes that deletion a break (REQ-AUDIT).
"""

from tutor_api.adapters.persistence.migration_session import MigrationSession
from tutor_api.adapters.persistence.schema import SessionChainHead

revision = "b7e2c4a91d05"
down_revision = "c3a91e7b04d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    session = MigrationSession()
    session.execute(SessionChainHead().statements())


def downgrade() -> None:
    session = MigrationSession()
    session.execute(SessionChainHead().downgrade_statements())
