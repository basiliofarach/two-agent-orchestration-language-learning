"""Build the dataset from the pinned sources (SIMULATION §7.2, stage build).

Every artefact is read through ``SourceFetchPort``, so its digest is checked
on every build. Author-written payloads are committed files, checked against
the same ``sources.json`` digest. The CEFR-J Grammar Profile is pending
(DATASET §3.1): until it is confirmed the knowledge base is CEFR-SP
sentences only, and a benign case targets a sentence topic.
"""

import csv
import hashlib
import io
import tarfile
from pathlib import Path, PurePosixPath

import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict, Field

from tutor_sim.application.cases import CasePlanner, PrototypeExpectations
from tutor_sim.application.kb_corpus import CefrSpLoader, KbCorpusBuilder
from tutor_sim.application.payloads import (
    PayloadBankBuilder,
    SplitAssigner,
    SyntheticPiiGenerator,
)
from tutor_sim.application.personas import (
    ErrorProfileLoader,
    PersonaCardBuilder,
    RosterBuilder,
    TutorRoleCards,
)
from tutor_sim.application.realise import PlanFile, RealisePlan, ReleaseTree
from tutor_sim.domain.models.grammar import CefrSpRow, CefrSpSubset
from tutor_sim.domain.models.identity import SimulationNamespace
from tutor_sim.domain.models.kb import CefrLevel, KbDocumentRecord
from tutor_sim.domain.models.payload import Payload, PayloadCategory, PayloadDraft
from tutor_sim.domain.models.source import SourceRecord
from tutor_sim.domain.models.storage import DatasetTree, DatasetWrite
from tutor_sim.domain.ports.dataset_store import DatasetStorePort
from tutor_sim.domain.ports.source_fetch import SourceFetchPort

_LEVELS: tuple[CefrLevel, ...] = ("A1", "A2", "B1", "B2")
_SUBSET_DIRECTORY: dict[CefrSpSubset, str] = {
    "wiki-auto": "Wiki-Auto",
    "score": "SCoRE",
}
# Per source, so one large set cannot crowd out the others. 70% of 100 is
# 70 test payloads, above the 60 a category needs (DATASET §3.3).
_PER_SOURCE = 100
_MAX_PAYLOAD_CHARACTERS = 500
_AUTHORED: dict[str, PayloadCategory] = {
    "author-open-web": "open_web",
    "author-history-probe": "history_probe",
    "author-proficiency": "proficiency",
}
_SYNTHETIC_PII = 100


class BuildFailure(ValueError):
    """A source the build needs is missing, or its content cannot be used."""


class SourceIndex:
    """Admitted sources by id. The build names each source it reads."""

    def __init__(self, sources: tuple[SourceRecord, ...]) -> None:
        self._by_id = {source.source_id: source for source in sources}

    def get(self, source_id: str) -> SourceRecord:
        """The record, or a build failure naming the absent id."""
        record = self._by_id.get(source_id)
        if record is None:
            msg = f"{source_id} is not in sources.json"
            raise BuildFailure(msg)
        return record


class TarTexts:
    """UTF-8 members of a gzip tarball whose path matches a directory and suffix."""

    def read(
        self, body: bytes, directory: str, suffix: str
    ) -> tuple[tuple[str, str], ...]:
        """``(member name, text)`` pairs, sorted by name so a build repeats."""
        found: list[tuple[str, str]] = []
        with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as archive:
            for member in archive.getmembers():
                path = PurePosixPath(member.name)
                if not member.isfile() or path.suffix != suffix:
                    continue
                if directory not in path.parts:
                    continue
                handle = archive.extractfile(member)
                if handle is None:  # pragma: no cover - isfile() rules this out
                    continue
                found.append((member.name, handle.read().decode("utf-8")))
        return tuple(sorted(found))


class CefrSpArchive:
    """The CEFR-SP tarball: ``sentence<TAB>level A<TAB>level B`` per line."""

    def __init__(self, texts: TarTexts) -> None:
        self._texts = texts

    def rows(self, body: bytes, subset: CefrSpSubset) -> tuple[CefrSpRow, ...]:
        """Every well-formed line of one subset. The loader checks agreement."""
        rows: list[CefrSpRow] = []
        for name, text in self._texts.read(body, _SUBSET_DIRECTORY[subset], ".txt"):
            stem = PurePosixPath(name).stem
            for number, line in enumerate(text.splitlines(), start=1):
                fields = line.split("\t")
                if len(fields) != 3:
                    continue
                rows.append(
                    CefrSpRow(
                        sentence_id=f"{subset}/{stem}/{number}",
                        text=fields[0],
                        level_a=fields[1],
                        level_b=fields[2],
                        subset=subset,
                    )
                )
        if not rows:
            msg = f"CEFR-SP {subset} has no rows"
            raise BuildFailure(msg)
        return tuple(rows)


class ParquetColumns:
    """Named columns of a Parquet file, as Python values, row by row."""

    def rows(
        self, body: bytes, names: tuple[str, ...]
    ) -> tuple[tuple[object, ...], ...]:
        """One tuple per row, in the order ``names`` gives."""
        table = pq.read_table(io.BytesIO(body), columns=list(names))
        columns = [table.column(name).to_pylist() for name in names]
        return tuple(zip(*columns, strict=True))


class PayloadText:
    """The text a payload may carry: stripped, non-blank, not overlong."""

    def usable(self, value: object) -> str | None:
        """The stripped text, or nothing when it cannot be planted verbatim."""
        if not isinstance(value, str):
            return None
        text = value.strip()
        if not text or len(text) > _MAX_PAYLOAD_CHARACTERS:
            return None
        return text


class PayloadSample:
    """A fixed subset per source: the texts with the smallest SHA-256.

    There is no random draw, so the same artefact gives the same sample.
    """

    def take(
        self, drafts: tuple[PayloadDraft, ...], limit: int
    ) -> tuple[PayloadDraft, ...]:
        """At most ``limit`` drafts, one per distinct text."""
        unique = {draft.text: draft for draft in drafts}
        ordered = sorted(
            unique.values(),
            key=lambda draft: hashlib.sha256(draft.text.encode()).hexdigest(),
        )
        return tuple(ordered[:limit])


class InjectionPayloads:
    """Direct-injection payloads from deepset and HackAPrompt."""

    def __init__(self, columns: ParquetColumns, text: PayloadText) -> None:
        self._columns = columns
        self._text = text

    def deepset(self, source: SourceRecord, body: bytes) -> tuple[PayloadDraft, ...]:
        """Rows labelled 1, the injection class."""
        return tuple(
            self._draft(source, text)
            for value, label in self._columns.rows(body, ("text", "label"))
            if label == 1 and (text := self._text.usable(value)) is not None
        )

    def hackaprompt(
        self, source: SourceRecord, body: bytes
    ) -> tuple[PayloadDraft, ...]:
        """User inputs that succeeded against the competition's target model."""
        return tuple(
            self._draft(source, text)
            for value, correct in self._columns.rows(body, ("user_input", "correct"))
            if correct is True and (text := self._text.usable(value)) is not None
        )

    def _draft(self, source: SourceRecord, text: str) -> PayloadDraft:
        return PayloadDraft(
            category="direct_injection",
            text=text,
            source_id=source.source_id,
            licence=source.licence,
            redistributable=source.redistributable,
        )


class MinorBenchPayloads:
    """Child-safety prompts from MinorBench's ``Prompt`` column."""

    def __init__(self, text: PayloadText) -> None:
        self._text = text

    def drafts(self, source: SourceRecord, body: bytes) -> tuple[PayloadDraft, ...]:
        """One draft per usable prompt."""
        reader = csv.DictReader(io.StringIO(body.decode("utf-8-sig")))
        if reader.fieldnames is None or "Prompt" not in reader.fieldnames:
            msg = "MinorBench has no Prompt column"
            raise BuildFailure(msg)
        return tuple(
            PayloadDraft(
                category="child_safety",
                text=text,
                source_id=source.source_id,
                licence=source.licence,
                redistributable=source.redistributable,
            )
            for row in reader
            if (text := self._text.usable(row.get("Prompt"))) is not None
        )


class AuthoredLine(BaseModel):
    """One author-written payload line."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=1)


class AuthoredPayloads:
    """Committed author-written payloads, checked against ``sources.json``."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def drafts(self, source: SourceRecord) -> tuple[PayloadDraft, ...]:
        """Every line of ``authored/<source_id>.jsonl``. A changed file is refused."""
        category = _AUTHORED.get(source.source_id)
        if category is None:
            msg = f"{source.source_id} is not an author-written source"
            raise BuildFailure(msg)
        path = self._directory / f"{source.source_id}.jsonl"
        if not path.is_file():
            msg = f"{path.name} is missing"
            raise BuildFailure(msg)
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != source.sha256:
            msg = f"{source.source_id} digest mismatch"
            raise BuildFailure(msg)
        return tuple(
            PayloadDraft(
                category=category,
                text=AuthoredLine.model_validate_json(line).text,
                source_id=source.source_id,
                licence=source.licence,
                redistributable=source.redistributable,
            )
            for line in body.decode("utf-8").splitlines()
            if line.strip()
        )


class SentenceTopics:
    """Benign topics by level, while the KB has no grammar items."""

    def by_level(
        self, documents: tuple[KbDocumentRecord, ...]
    ) -> dict[CefrLevel, tuple[str, ...]]:
        """The sentence-document topics at each level. A level with none fails."""
        topics: dict[CefrLevel, tuple[str, ...]] = {}
        for level in _LEVELS:
            found = sorted(
                {
                    document.topic_id
                    for document in documents
                    if document.partition == "default" and document.cefr_level == level
                }
            )
            if not found:
                msg = f"the knowledge base has no {level} document"
                raise BuildFailure(msg)
            topics[level] = tuple(found)
        return topics


class BuildSummary(BaseModel):
    """What one build wrote. The command prints it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    documents: int = Field(ge=0)
    kb_tree: DatasetTree
    payloads: int = Field(ge=0)
    cases: int = Field(ge=0)
    episodes: int = Field(ge=0)
    personas: int = Field(ge=0)

    def line(self) -> str:
        """One line for the operator."""
        return (
            f"built {self.documents} KB documents ({self.kb_tree}), "
            f"{self.payloads} payloads, {self.personas} personas, "
            f"{self.cases} cases, {self.episodes} episodes"
        )


class JsonLines:
    """JSONL bytes for a run of frozen models."""

    def body(self, records: tuple[BaseModel, ...]) -> bytes:
        """One record per line, with a final newline."""
        return "".join(record.model_dump_json() + "\n" for record in records).encode()


class DatasetBuild:
    """Read the pinned sources and write the dataset and the case plan.

    Files whose content any non-redistributable source fed go to
    ``restricted/``; the rest go to ``public/``. ``plan.json`` holds payload
    text, so it is written beside the trees, where ``.gitignore`` keeps it.
    """

    def __init__(
        self,
        fetch: SourceFetchPort,
        store: DatasetStorePort,
        sources: tuple[SourceRecord, ...],
        dataset_dir: Path,
        seed: int,
    ) -> None:
        self._fetch = fetch
        self._store = store
        self._sources = SourceIndex(sources)
        self._dataset_dir = dataset_dir
        self._seed = seed
        self._lines = JsonLines()
        self._namespace = SimulationNamespace()

    def run(self) -> BuildSummary:
        """Build every file. A failure leaves no plan behind."""
        documents, kb_tree = self._knowledge_base()
        cards = PersonaCardBuilder(ErrorProfileLoader()).cards()
        payloads = PayloadBankBuilder(SplitAssigner()).build(
            self._payload_drafts(), self._seed
        )
        canary = next(
            document.canary for document in documents if document.canary is not None
        )
        expectations = PrototypeExpectations()
        cases, episodes = CasePlanner(expectations).plan(
            cards, SentenceTopics().by_level(documents), payloads, canary
        )
        self._write("kb/documents.jsonl", self._lines.body(documents), kb_tree)
        for card in cards:
            self._write(
                f"personas/{card.persona_id}.json",
                card.model_dump_json(indent=2).encode() + b"\n",
                "public",
            )
        for role in TutorRoleCards().cards():
            self._write(
                f"tutors/{role.role}.json",
                role.model_dump_json(indent=2).encode() + b"\n",
                "public",
            )
        roster = RosterBuilder(self._namespace).roster(cards)
        self._write("learners/roster.jsonl", self._lines.body(roster), "public")
        table = expectations.table()
        self._write(
            f"expectations/{table.policy_version}.json",
            table.model_dump_json(indent=2).encode() + b"\n",
            "public",
        )
        self._payload_files(payloads)
        PlanFile().write(
            self._dataset_dir / "plan.json",
            RealisePlan(
                dataset_version=cases[0].dataset_version,
                policy_version=table.policy_version,
                seed=self._seed,
                cases=cases,
                payloads=payloads,
                episodes=episodes,
            ),
        )
        return BuildSummary(
            documents=len(documents),
            kb_tree=kb_tree,
            payloads=len(payloads),
            cases=len(cases),
            episodes=len(episodes),
            personas=len(cards),
        )

    def _knowledge_base(self) -> tuple[tuple[KbDocumentRecord, ...], DatasetTree]:
        archive = CefrSpArchive(TarTexts())
        rows: list[CefrSpRow] = []
        flags: list[bool] = []
        subsets: tuple[tuple[str, CefrSpSubset], ...] = (
            ("cefr-sp-wiki-auto", "wiki-auto"),
            ("cefr-sp-score", "score"),
        )
        for source_id, subset in subsets:
            source = self._sources.get(source_id)
            rows.extend(archive.rows(self._fetch.fetch(source), subset))
            flags.append(source.redistributable)
        sentences = CefrSpLoader().load(tuple(rows))
        documents = KbCorpusBuilder(self._namespace).build(sentences, (), ())
        return documents, ReleaseTree().choose(tuple(flags))

    def _payload_drafts(self) -> tuple[PayloadDraft, ...]:
        text = PayloadText()
        sample = PayloadSample()
        injections = InjectionPayloads(ParquetColumns(), text)
        deepset = self._sources.get("deepset-prompt-injections")
        hackaprompt = self._sources.get("hackaprompt")
        minorbench = self._sources.get("minorbench")
        authored = AuthoredPayloads(self._dataset_dir / "public" / "authored")
        drafts: list[PayloadDraft] = []
        drafts.extend(
            sample.take(
                injections.deepset(deepset, self._fetch.fetch(deepset)), _PER_SOURCE
            )
        )
        drafts.extend(
            sample.take(
                injections.hackaprompt(hackaprompt, self._fetch.fetch(hackaprompt)),
                _PER_SOURCE,
            )
        )
        drafts.extend(
            sample.take(
                MinorBenchPayloads(text).drafts(
                    minorbench, self._fetch.fetch(minorbench)
                ),
                _PER_SOURCE,
            )
        )
        for source_id in _AUTHORED:
            drafts.extend(authored.drafts(self._sources.get(source_id)))
        # Generated, not fetched; it must still be an admitted source.
        self._sources.get("synthetic-pii")
        drafts.extend(SyntheticPiiGenerator().generate(self._seed, _SYNTHETIC_PII))
        return tuple(drafts)

    def _payload_files(self, payloads: tuple[Payload, ...]) -> None:
        grouped: dict[tuple[PayloadCategory, DatasetTree], list[Payload]] = {}
        for payload in payloads:
            tree: DatasetTree = "public" if payload.redistributable else "restricted"
            grouped.setdefault((payload.category, tree), []).append(payload)
        for (category, tree), group in sorted(grouped.items()):
            self._write(
                f"payloads/{category}.jsonl", self._lines.body(tuple(group)), tree
            )

    def _write(self, relative: str, body: bytes, tree: DatasetTree) -> None:
        self._store.write(
            DatasetWrite(
                relative_path=relative,
                body=body,
                redistributable=tree == "public",
                tree=tree,
            )
        )
