"""Record a refusal and the cited text; approve only what passed every gate.

The review of 9318350b09d1 found three gaps in what a turn record proves.
A refusal before the model stored no outcome, so the flags that caused it
never reached the log. The flags raised on the prompt were dropped after
the permission decision. And a replay rendered today's corpus text with no
way to tell it from the text the turn was generated from. Separately,
approve was accepted on a draft a gate had held, so the post-generation
gates did not change what a tutor could release.
"""

from tutor_api.adapters.persistence.migration_session import MigrationSession
from tutor_api.adapters.persistence.schema import (
    ReleaseRequiresPassedGates,
    TurnAuditEvidence,
)

revision = "5e1f0c7a9b23"
down_revision = "9318350b09d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    session = MigrationSession()
    session.execute(TurnAuditEvidence().statements())
    session.execute(ReleaseRequiresPassedGates().statements())


def downgrade() -> None:
    session = MigrationSession()
    session.execute(ReleaseRequiresPassedGates().downgrade_statements())
    session.execute(TurnAuditEvidence().downgrade_statements())
