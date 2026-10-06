"""Write the evidence pack. ``make evidence`` from ``tutor-api/``."""

import asyncio
import sys
from pathlib import Path
from typing import cast

from tutor_api.adapters.persistence.audit_query import (
    AuditRecordDecoder,
    PostgresAuditQuery,
)
from tutor_api.adapters.persistence.database import DatabaseEngine
from tutor_api.adapters.persistence.database_url import (
    DriverSwap,
    MigrationDatabaseUrl,
)
from tutor_api.adapters.persistence.sealed import SealedValue
from tutor_api.adapters.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tutor_api.container import ApplicationContainer
from tutor_api.curation.prototype_seed import FixedSettingsProvider
from tutor_api.evidence.pack import EvidencePack, EvidenceSources, RepositoryPins
from tutor_api.evidence.survey import ChainSurvey, ChainSurveyResult
from tutor_api.settings import ApplicationSettings
from tutor_core.domain.audit.chain import ChainVerifier
from tutor_core.domain.ports.cipher import CipherPort
from tutor_core.domain.ports.clock import ClockPort


class PackPaths:
    """Find the workspace root by ``uv.lock``, searching up from ``start``."""

    def __init__(self, start: Path) -> None:
        self._start = start

    def root(self) -> Path:
        """The nearest directory above ``start`` that contains ``uv.lock``."""
        for parent in self._start.resolve().parents:
            if (parent / "uv.lock").is_file():
                return parent
        msg = "uv.lock was not found"
        raise FileNotFoundError(msg)


class ModelPin:
    """Read the pinned weights SHA from the model pin file."""

    def revision(self, path: Path | None) -> str:
        """The ``weights_sha`` value, or ``unpinned`` when there is none."""
        if path is None:
            return "unpinned"
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("weights_sha"):
                return line.split("=", 1)[1].strip().strip('"')
        return "unpinned"


class EvidenceMain:
    """Compose the pack from the log, on the owner URL, as the seed does.

    The chain status and the policy version are read from the database by
    ``ChainSurvey``, never supplied as constants. The cipher, clock and
    verifier are the container's, so the pack opens the log with the
    deployment's key and stamps it with the injected clock (DEC-0010).
    """

    def __init__(self, root: Path, destination: Path) -> None:
        self._root = root
        self._destination = destination

    async def run(self, settings: ApplicationSettings) -> int:
        """Survey the log, write the pack, and return an exit code."""
        container = ApplicationContainer(FixedSettingsProvider(settings)).build()
        cipher = cast(CipherPort, container.resolve(CipherPort))
        clock = cast(ClockPort, container.resolve(ClockPort))
        verifier = cast(ChainVerifier, container.resolve(ChainVerifier))
        survey = await self._survey(settings, cipher, verifier)
        pins = RepositoryPins(self._root)
        sources = EvidenceSources(
            commit=pins.commit(),
            lockfile_sha256=pins.lockfile_sha256(),
            model_revision=ModelPin().revision(settings.model_pin_path),
            runtime=sys.version.split()[0],
            policy_version=survey.policy_version or "none-published",
            chain_status=survey.chain_status(),
            field_label="synthetic-only",
            sessions=survey.sessions,
            turns=survey.turns,
            actions=survey.actions,
            unchained_actions=survey.unchained_actions,
            broken_sessions=tuple(str(item) for item in survey.broken_sessions),
        )
        EvidencePack(clock).write(self._destination, sources)
        sys.stdout.write(
            f"wrote {self._destination} chain_status={sources.chain_status}\n"
        )
        return 0

    async def _survey(
        self,
        settings: ApplicationSettings,
        cipher: CipherPort,
        verifier: ChainVerifier,
    ) -> ChainSurveyResult:
        owner = DriverSwap("postgresql+asyncpg").apply(
            MigrationDatabaseUrl(settings).value()
        )
        engine = DatabaseEngine(owner)
        result = ChainSurveyResult()
        try:
            connection = await engine.connect()
            query = PostgresAuditQuery(
                connection, AuditRecordDecoder(SealedValue(cipher))
            )
            await SqlAlchemyUnitOfWork(connection).run(
                ChainSurvey(query, verifier, result)
            )
        finally:
            await engine.dispose()
        return result


if __name__ == "__main__":  # pragma: no cover
    root = PackPaths(Path(__file__)).root()
    raise SystemExit(
        asyncio.run(EvidenceMain(root, root / "evidence").run(ApplicationSettings()))
    )
