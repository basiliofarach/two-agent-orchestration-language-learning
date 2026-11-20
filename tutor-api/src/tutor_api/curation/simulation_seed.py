"""Seed a simulation database from C1 and C2. The request role cannot.

Run as the migration owner. ``--stress`` is the only way the fault partition
is ingested. A second run inserts nothing.

    uv run python -m tutor_api.curation.simulation_seed
"""

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, TextIO, TypeVar, cast
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

from tutor_api.adapters.llm.local_embedding import LocalEmbedding
from tutor_api.adapters.persistence.database import DatabaseEngine
from tutor_api.adapters.persistence.database_url import DriverSwap, MigrationDatabaseUrl
from tutor_api.adapters.persistence.knowledge_base import (
    ChunkIdentifiers,
    PassageSplitter,
    PostgresCorpusIngestion,
    VectorLiteral,
)
from tutor_api.adapters.persistence.learner_history import HistoryOutcomeCodec
from tutor_api.adapters.persistence.schema import BaseSchema
from tutor_api.adapters.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tutor_api.container import ApplicationContainer
from tutor_api.curation.prototype_seed import (
    FixedSettingsProvider,
    PrototypePlan,
    PublishedVersion,
    PublishPolicy,
)
from tutor_api.di.container import Container
from tutor_api.settings import ApplicationSettings
from tutor_core.domain.models.corpus import (
    CefrLevel,
    CorpusDocument,
    ReviewStatus,
)
from tutor_core.domain.ports.cipher import CipherPort
from tutor_core.domain.ports.clock import ClockPort
from tutor_core.domain.ports.unit_of_work import (
    TransactionalWork,
    TransactionConnection,
)


class OperatorRole:
    """The seed is an operator command. The request role has no such grant."""

    def require_owner(self, role: str) -> None:
        """Refuse every role but the owner."""
        if role != "owner":
            msg = "the request role cannot ingest or enrol"
            raise PermissionError(msg)


class SeedDocument(BaseModel):
    """The C1 fields the seed ingests. Other columns are ignored."""

    model_config = ConfigDict(extra="ignore")

    document_id: UUID
    source_uri: str = Field(min_length=1)
    version: str = Field(min_length=1)
    review_status: ReviewStatus
    licence: str = Field(min_length=1)
    cefr_level: CefrLevel
    level_method: str = Field(min_length=1)
    content: str = Field(min_length=1)
    partition: Literal["default", "faults"] = "default"

    def corpus(self) -> CorpusDocument:
        """The document the ingestion port accepts."""
        return CorpusDocument(
            document_id=self.document_id,
            source_uri=self.source_uri,
            version=self.version,
            review_status=self.review_status,
            licence=self.licence,
            cefr_level=self.cefr_level,
            level_method=self.level_method,
            content=self.content,
        )


class SeedEvent(BaseModel):
    """One history row. The instant is the clock minus ``days_before_seed``."""

    model_config = ConfigDict(extra="ignore")

    item_id: str = Field(min_length=1)
    correct: bool
    days_before_seed: int = Field(ge=0)


class SeedLearner(BaseModel):
    """A C2 roster row."""

    model_config = ConfigDict(extra="ignore")

    persona_id: str = Field(min_length=1)
    learner_id: UUID
    pseudonym: str = Field(min_length=1)
    proficiency_level: str = Field(min_length=1)
    history: tuple[SeedEvent, ...] = ()


_Row = TypeVar("_Row", SeedDocument, SeedLearner)


class JsonlFile:
    """One JSON object per line. Blank lines are skipped."""

    def documents(self, path: Path) -> tuple[SeedDocument, ...]:
        """C1."""
        return tuple(self._rows(path, SeedDocument))

    def learners(self, path: Path) -> tuple[SeedLearner, ...]:
        """C2."""
        return tuple(self._rows(path, SeedLearner))

    def _rows(self, path: Path, model: type[_Row]) -> list[_Row]:
        if not path.is_file():
            msg = f"{path.name} is not a seed file"
            raise FileNotFoundError(msg)
        rows: list[_Row] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rows.append(model.model_validate_json(line))
        return rows


class FaultPartition:
    """The fault partition is ingested only when the operator passes stress."""

    def select(
        self, documents: tuple[SeedDocument, ...], stress: bool
    ) -> tuple[SeedDocument, ...]:
        """Default documents always. Fault documents only under stress."""
        return tuple(
            document
            for document in documents
            if document.partition == "default" or stress
        )


class HistoryInstants:
    """Turn ``days_before_seed`` into a UTC instant from the injected clock."""

    def __init__(self, clock: ClockPort) -> None:
        self._clock = clock

    def occurred_at(self, days_before: int) -> datetime:
        """The event's instant. A naive clock is refused."""
        instant = self._clock.now()
        if instant.utcoffset() is None:
            msg = "the seed clock must be timezone-aware"
            raise ValueError(msg)
        return instant - timedelta(days=days_before)


class EventIdentity:
    """A stable id, so a second seed finds the same history row."""

    def of(self, learner_id: UUID, item_id: str) -> UUID:
        """uuid5 of the learner and the item."""
        namespace = UUID("10000000-0000-4000-8000-0000000000aa")
        return uuid5(namespace, f"{learner_id}:{item_id}")


class SeedTally(BaseModel):
    """How many rows this run inserted. A re-run leaves these at zero."""

    model_config = ConfigDict(extra="forbid")

    documents: int = 0
    passages: int = 0
    present: int = 0
    learners: int = 0
    events: int = 0

    def line(self) -> str:
        """The completed log line the operator sees."""
        return (
            f"seeded {self.documents} documents ({self.passages} passages, "
            f"each embedded), {self.learners} learners, {self.events} history "
            f"events; {self.present} documents were already present"
        )


class SeedProgress:
    """A one-line bar of embedded passages. Silent when the stream is not a TTY.

    The stream is injected, so a test reads what an operator would see.
    """

    def __init__(self, stream: TextIO, width: int = 30) -> None:
        self._stream = stream
        self._width = width
        self._total = 0
        self._done = 0
        self._live = stream.isatty()

    def start(self, total: int) -> None:
        """The number of passages this run may embed."""
        self._total = total
        self._done = 0

    def working(self, label: str) -> None:
        """Show which document is being embedded now."""
        self._draw(f"embedding {label}")

    def advance(self, passages: int) -> None:
        """Count a document's passages as done."""
        self._done += passages
        self._draw("")

    def close(self) -> None:
        """End the bar's line so the summary starts on its own."""
        if self._live and self._total:
            self._stream.write("\n")
            self._stream.flush()

    def _draw(self, label: str) -> None:
        if not self._live or not self._total:
            return
        filled = self._width * self._done // self._total
        bar = "#" * filled + "-" * (self._width - filled)
        percent = 100 * self._done // self._total
        line = f"\r  [{bar}] {percent:3d}% {self._done}/{self._total} {label}"
        self._stream.write(line.ljust(100)[:100])
        self._stream.flush()


class IngestCatalogue(TransactionalWork):
    """Ingest the selected documents and enrol the learners, skipping rows present."""

    def __init__(
        self,
        documents: tuple[SeedDocument, ...],
        learners: tuple[SeedLearner, ...],
        cipher: CipherPort,
        clock: ClockPort,
        tally: SeedTally,
        progress: SeedProgress | None = None,
    ) -> None:
        self._documents = documents
        self._learners = learners
        self._cipher = cipher
        self._clock = clock
        self._tally = tally
        self._progress = progress
        self._when = HistoryInstants(clock)
        self._ids = EventIdentity()

    async def run(self, connection: TransactionConnection) -> None:
        """Write what is not there yet."""
        await self._documents_of(connection)
        await self._learners_of(connection)

    async def _documents_of(self, connection: TransactionConnection) -> None:
        splitter = PassageSplitter()
        sizes = [len(splitter.split(document.content)) for document in self._documents]
        if self._progress is not None:
            self._progress.start(sum(sizes))
        for document, size in zip(self._documents, sizes, strict=True):
            row = await connection.fetch_one(
                "SELECT 1 FROM kb_document WHERE id = :id",
                {"id": document.document_id},
            )
            if row is not None:
                self._tally.present += 1
                if self._progress is not None:
                    self._progress.advance(size)
                continue
            if self._progress is not None:
                self._progress.working(document.source_uri)
            ingestion = PostgresCorpusIngestion(
                connection,
                LocalEmbedding(BaseSchema().embedding_dimensions()),
                self._cipher,
                ChunkIdentifiers(),
                PassageSplitter(),
                VectorLiteral(),
            )
            await ingestion.ingest(document.corpus())
            self._tally.documents += 1
            self._tally.passages += size
            if self._progress is not None:
                self._progress.advance(size)
        if self._progress is not None:
            self._progress.close()

    async def _learners_of(self, connection: TransactionConnection) -> None:
        now = self._clock.now()
        for learner in self._learners:
            row = await connection.fetch_one(
                "SELECT 1 FROM learner WHERE learner_id = :id",
                {"id": learner.learner_id},
            )
            if row is None:
                await connection.execute(
                    """
                    INSERT INTO learner (
                        learner_id, pseudonym, proficiency_level, retain_until
                    ) VALUES (
                        :learner_id, :pseudonym, :proficiency, :retain_until
                    )
                    """,
                    {
                        "learner_id": learner.learner_id,
                        "pseudonym": self._seal(learner.pseudonym),
                        "proficiency": self._seal(learner.proficiency_level),
                        "retain_until": now + timedelta(days=365),
                    },
                )
                self._tally.learners += 1
            await self._events(connection, learner)

    async def _events(
        self, connection: TransactionConnection, learner: SeedLearner
    ) -> None:
        for event in learner.history:
            event_id = self._ids.of(learner.learner_id, event.item_id)
            row = await connection.fetch_one(
                "SELECT 1 FROM learner_history_event WHERE id = :id",
                {"id": event_id},
            )
            if row is not None:
                continue
            await connection.execute(
                """
                INSERT INTO learner_history_event (
                    id, learner_id, item_id, correct, occurred_at
                ) VALUES (
                    :id, :learner_id, :item_id, :correct, :occurred_at
                )
                """,
                {
                    "id": event_id,
                    "learner_id": learner.learner_id,
                    "item_id": self._seal(event.item_id),
                    "correct": self._cipher.encrypt(
                        HistoryOutcomeCodec().encode(event.correct)
                    ),
                    "occurred_at": self._when.occurred_at(event.days_before_seed),
                },
            )
            self._tally.events += 1

    def _seal(self, text: str) -> bytes:
        return self._cipher.encrypt(text.encode("utf-8"))


class SimulationSeed:
    """Publish the prototype card, then ingest C1 and enrol C2."""

    def __init__(self, engine: DatabaseEngine, container: Container) -> None:
        self._engine = engine
        self._container = container

    async def apply(
        self,
        documents: tuple[SeedDocument, ...],
        learners: tuple[SeedLearner, ...],
        threshold: float,
        progress: SeedProgress | None = None,
    ) -> SeedTally:
        """Insert what is missing. The tally counts only this call."""
        cipher = cast(CipherPort, self._container.resolve(CipherPort))
        clock = cast(ClockPort, self._container.resolve(ClockPort))
        plan = PrototypePlan().plan(threshold)
        found: list[bool] = []
        await self._unit(PublishedVersion(plan.policy_version, found))
        if not found[0]:
            await self._unit(PublishPolicy(plan, cipher, clock))
        tally = SeedTally()
        await self._unit(
            IngestCatalogue(documents, learners, cipher, clock, tally, progress)
        )
        return tally

    async def _unit(self, work: TransactionalWork) -> None:
        await SqlAlchemyUnitOfWork(await self._engine.connect()).run(work)


class SimulationSeedMain:
    """Compose the seed from settings the caller already validated."""

    async def run(
        self,
        settings: ApplicationSettings,
        documents: tuple[SeedDocument, ...],
        learners: tuple[SeedLearner, ...],
        stress: bool = False,
        role: str = "owner",
        progress: SeedProgress | None = None,
    ) -> SeedTally:
        """Seed and return the tally. The request role never opens a connection."""
        OperatorRole().require_owner(role)
        threshold = settings.conflict_confidence_threshold
        if threshold is None:
            msg = "CONFLICT_CONFIDENCE_THRESHOLD is not set. Export it."
            raise ValueError(msg)
        selected = FaultPartition().select(documents, stress)
        container = ApplicationContainer(FixedSettingsProvider(settings)).build()
        owner = DriverSwap("postgresql+asyncpg").apply(
            MigrationDatabaseUrl(settings).value()
        )
        engine = DatabaseEngine(owner)
        try:
            return await SimulationSeed(engine, container).apply(
                selected, learners, threshold, progress
            )
        finally:
            await engine.dispose()


class SeedProcess:
    """``simulation_seed [--stress] kb.jsonl roster.jsonl``."""

    def arguments(self, argv: list[str]) -> tuple[bool, Path, Path]:
        """``--stress`` is optional and must come first."""
        args = list(argv)
        stress = False
        if args and args[0] == "--stress":
            stress = True
            args = args[1:]
        if len(args) != 2:
            msg = "usage: simulation_seed [--stress] kb.jsonl roster.jsonl"
            raise ValueError(msg)
        return stress, Path(args[0]), Path(args[1])


def main(
    argv: list[str], settings: ApplicationSettings, stream: TextIO | None = None
) -> int:
    """Load the two files and seed. Progress and the summary go to ``stream``."""
    output = sys.stderr if stream is None else stream
    stress, documents, learners = SeedProcess().arguments(argv)
    loaded_documents = JsonlFile().documents(documents)
    loaded_learners = JsonlFile().learners(learners)
    progress = SeedProgress(output)

    async def _run() -> SeedTally:
        return await SimulationSeedMain().run(
            settings, loaded_documents, loaded_learners, stress, "owner", progress
        )

    tally = asyncio.run(_run())
    output.write(tally.line() + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:], ApplicationSettings()))
