"""Grant column-level history reads and seal item outcomes (DEC-0012)."""

from tutor_api.adapters.persistence.learner_history import HistoryOutcomeCodec
from tutor_api.adapters.persistence.migration_session import MigrationSession
from tutor_api.adapters.persistence.schema import (
    ApplicationRole,
    HistoryOutcomeEncryption,
    LearnerHistoryColumnGrant,
)
from tutor_api.container import ApplicationContainer, SettingsProvider
from tutor_api.settings import ApplicationSettings
from tutor_core.domain.ports.cipher import CipherPort

revision = "b7e2c4a91d08"
down_revision = "7f3c2a91e0b4"
branch_labels = None
depends_on = None


class MigrationCipher:
    """The application's cipher, built only when a row has to be sealed."""

    def __call__(self) -> CipherPort:
        cipher = ApplicationContainer(SettingsProvider()).build().resolve(CipherPort)
        if not isinstance(cipher, CipherPort):
            msg = "the container did not resolve a cipher"
            raise TypeError(msg)
        return cipher


def upgrade() -> None:
    session = MigrationSession()
    HistoryOutcomeEncryption().upgrade(
        session.driver(), MigrationCipher(), HistoryOutcomeCodec()
    )
    role = ApplicationRole(ApplicationSettings().postgres_app_user)
    session.execute(LearnerHistoryColumnGrant(role).statements())


def downgrade() -> None:
    session = MigrationSession()
    role = ApplicationRole(ApplicationSettings().postgres_app_user)
    session.execute(LearnerHistoryColumnGrant(role).downgrade_statements())
    HistoryOutcomeEncryption().downgrade(
        session.driver(), MigrationCipher(), HistoryOutcomeCodec()
    )
