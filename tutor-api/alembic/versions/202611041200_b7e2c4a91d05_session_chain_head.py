"""Anchor each session's turn-chain head outside the turn rows.

A deleted tail still links from the genesis hash. The head stored on the
session is what makes that deletion a break (REQ-AUDIT).
"""

from tutor_api.adapters.persistence.migration_session import MigrationSession
from tutor_api.adapters.persistence.schema import ApplicationRole, SessionChainHead
from tutor_api.settings import ApplicationSettings

revision = "b7e2c4a91d05"
down_revision = "c3a91e7b04d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    role = ApplicationRole(ApplicationSettings().postgres_app_user)
    session = MigrationSession()
    session.execute(SessionChainHead(role).statements())


def downgrade() -> None:
    role = ApplicationRole(ApplicationSettings().postgres_app_user)
    session = MigrationSession()
    session.execute(SessionChainHead(role).downgrade_statements())
