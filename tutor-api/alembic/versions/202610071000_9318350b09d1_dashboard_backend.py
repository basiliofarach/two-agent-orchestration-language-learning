"""Open sessions from the dashboard, chain tutor actions, record history.

The review of a7c3e91b04d2 found that approve and edit were accepted on a
stopped session, that tutor actions were outside any hash chain, that a
stop could be made without a logged action, and that replay could not
re-render a turn because the history it used was not recorded. Each is
closed here in the database, so no request path can skip it.
"""

from tutor_api.adapters.persistence.migration_session import MigrationSession
from tutor_api.adapters.persistence.schema import (
    ApplicationRole,
    HumanActionChain,
    OpenSessionFunction,
    SessionStartedAtGrant,
    StopRequiresAction,
    TurnAuditHistorySnapshot,
)
from tutor_api.settings import ApplicationSettings

revision = "9318350b09d1"
down_revision = "a7c3e91b04d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    role = ApplicationRole(ApplicationSettings().postgres_app_user)
    session = MigrationSession()
    session.execute(OpenSessionFunction(role).statements())
    session.execute(SessionStartedAtGrant(role).statements())
    session.execute(HumanActionChain().statements())
    session.execute(StopRequiresAction(role).statements())
    session.execute(TurnAuditHistorySnapshot().statements())


def downgrade() -> None:
    role = ApplicationRole(ApplicationSettings().postgres_app_user)
    session = MigrationSession()
    session.execute(TurnAuditHistorySnapshot().downgrade_statements())
    session.execute(StopRequiresAction(role).downgrade_statements())
    session.execute(HumanActionChain().downgrade_statements())
    session.execute(SessionStartedAtGrant(role).downgrade_statements())
    session.execute(OpenSessionFunction(role).downgrade_statements())
