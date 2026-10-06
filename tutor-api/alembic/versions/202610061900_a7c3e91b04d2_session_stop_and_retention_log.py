"""Stop a session from the application role, and log a retention purge.

The request path has no UPDATE on ``tutoring_session``. The function is the
only way a tutor stop sets ``stopped_at``. The purge log is append-only and
holds no learner text.
"""

from tutor_api.adapters.persistence.migration_session import MigrationSession
from tutor_api.adapters.persistence.schema import (
    ApplicationRole,
    MarkSessionStopped,
    RetentionPurgeLog,
)
from tutor_api.settings import ApplicationSettings

revision = "a7c3e91b04d2"
down_revision = "c4d8e2f61a37"
branch_labels = None
depends_on = None


def upgrade() -> None:
    role = ApplicationRole(ApplicationSettings().postgres_app_user)
    session = MigrationSession()
    session.execute(MarkSessionStopped(role).statements())
    session.execute(RetentionPurgeLog(role).statements())


def downgrade() -> None:
    role = ApplicationRole(ApplicationSettings().postgres_app_user)
    session = MigrationSession()
    session.execute(RetentionPurgeLog(role).downgrade_statements())
    session.execute(MarkSessionStopped(role).downgrade_statements())
