"""Grant the session check and the history-event id tie-break.

The session read is column-level (DEC-0001). The event id is granted again
so a catalogue that applied the history grant before ``id`` was listed can
``ORDER BY id``. A fresh upgrade already holds that column; granting it
twice changes nothing.
"""

from tutor_api.adapters.persistence.migration_session import MigrationSession
from tutor_api.adapters.persistence.schema import (
    ApplicationRole,
    LearnerHistoryEventIdGrant,
    TutoringSessionColumnGrant,
)
from tutor_api.settings import ApplicationSettings

revision = "e5b9c1a04f77"
down_revision = "b7e2c4a91d08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    role = ApplicationRole(ApplicationSettings().postgres_app_user)
    session = MigrationSession()
    session.execute(LearnerHistoryEventIdGrant(role).statements())
    session.execute(TutoringSessionColumnGrant(role).statements())


def downgrade() -> None:
    role = ApplicationRole(ApplicationSettings().postgres_app_user)
    session = MigrationSession()
    session.execute(TutoringSessionColumnGrant(role).downgrade_statements())
    session.execute(LearnerHistoryEventIdGrant(role).downgrade_statements())
