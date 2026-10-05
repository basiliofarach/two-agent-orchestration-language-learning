"""Grant the application role read access to the request-path tables (DEC-0014)."""

from tutor_api.adapters.persistence.migration_session import MigrationSession
from tutor_api.adapters.persistence.schema import (
    ApplicationRole,
    RequestPathPrivileges,
)
from tutor_api.settings import ApplicationSettings

revision = "7f3c2a91e0b4"
down_revision = "b10e6c0875e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    role = ApplicationRole(ApplicationSettings().postgres_app_user)
    MigrationSession().execute(RequestPathPrivileges(role).statements())


def downgrade() -> None:
    role = ApplicationRole(ApplicationSettings().postgres_app_user)
    MigrationSession().execute(RequestPathPrivileges(role).downgrade_statements())
