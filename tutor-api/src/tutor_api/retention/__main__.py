"""Run the retention purge. ``make purge`` from ``tutor-api/``."""

import asyncio
import sys
from typing import cast

from tutor_api.adapters.persistence.database import DatabaseEngine
from tutor_api.adapters.persistence.database_url import (
    DriverSwap,
    MigrationDatabaseUrl,
)
from tutor_api.adapters.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tutor_api.container import ApplicationContainer
from tutor_api.curation.prototype_seed import FixedSettingsProvider
from tutor_api.retention.purge import PurgeLog, RetentionPurge
from tutor_api.settings import ApplicationSettings
from tutor_core.domain.ports.cipher import CipherPort
from tutor_core.domain.ports.clock import ClockPort


class RetentionMain:
    """Compose the purge on the owner URL, as the seed does, and run it once.

    The cipher and the clock come from the same container the API builds,
    so the tombstone is sealed with the deployment's key and the instant is
    the injected clock's (DEC-0010).
    """

    async def run(self, settings: ApplicationSettings) -> int:
        """Purge, print one line per learner, and return an exit code."""
        container = ApplicationContainer(FixedSettingsProvider(settings)).build()
        cipher = cast(CipherPort, container.resolve(CipherPort))
        clock = cast(ClockPort, container.resolve(ClockPort))
        owner = DriverSwap("postgresql+asyncpg").apply(
            MigrationDatabaseUrl(settings).value()
        )
        engine = DatabaseEngine(owner)
        log = PurgeLog()
        try:
            unit = SqlAlchemyUnitOfWork(await engine.connect())
            await unit.run(RetentionPurge(cipher, clock, log))
        finally:
            await engine.dispose()
        for receipt in log.receipts:
            sys.stdout.write(
                f"purged learner={receipt.learner_id} "
                f"history_rows={receipt.history_rows} "
                f"sessions_stopped={receipt.sessions_stopped}\n"
            )
        sys.stdout.write(f"purged {len(log.receipts)} learner(s)\n")
        return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(asyncio.run(RetentionMain().run(ApplicationSettings())))
