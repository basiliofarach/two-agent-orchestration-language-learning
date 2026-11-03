"""Record the licence and the level beside a knowledge-base document.

The three columns are ciphertext. A row ingested before this revision
carries none of them and stays unlevelled; the database holds no key,
so nothing is backfilled (DEC-0012, DEC-0016).
"""

from tutor_api.adapters.persistence.migration_session import MigrationSession
from tutor_api.adapters.persistence.schema import KbDocumentProvenance

revision = "c3a91e7b04d8"
down_revision = "5e1f0c7a9b23"
branch_labels = None
depends_on = None


def upgrade() -> None:
    session = MigrationSession()
    session.execute(KbDocumentProvenance().statements())


def downgrade() -> None:
    session = MigrationSession()
    session.execute(KbDocumentProvenance().downgrade_statements())
