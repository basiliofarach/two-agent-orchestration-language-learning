"""Measures that read CEFR-J through TreeTagger (SIMULATION §9.5).

* **Level fit**: of a released reply's words the CEFR-J wordlist lists,
  the share at or below the persona's level.
* **Pupil level**: the same share for the pupil's own message, so the
  persona's level can be checked against what the role model wrote.
* **Target structure (I2)**: whether a released exercise matches its
  grammar item's regex on the tagged text.

The wordlist lists headwords (``play``), not forms (``played``), so each
word is looked up by its TreeTagger lemma. Text is read, measured and
dropped: only counts and shares reach the run directory. None of this is
a quality grade; it is a pattern match and a word count.
"""

import io
import math
import zipfile
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from tutor_sim.application.grammar_profile import (
    GrammarProfileWorkbook,
    WorkbookUnreadable,
    XlsxSheets,
)
from tutor_sim.application.kb_corpus import LevelOrder, TargetStructureCheck
from tutor_sim.application.progress import CommandProgress
from tutor_sim.domain.models.case import StimulusCase
from tutor_sim.domain.models.episode import EpisodeTurn
from tutor_sim.domain.models.grammar import TaggedToken, WordLevel
from tutor_sim.domain.models.kb import CefrLevel
from tutor_sim.domain.models.measures import (
    CoverageSummary,
    MeasuredText,
    TargetStructureRow,
    TextKind,
)
from tutor_sim.domain.models.observation import Observation
from tutor_sim.domain.models.persona import PersonaCard, PupilLevel
from tutor_sim.domain.models.source import SourceRecord
from tutor_sim.domain.ports.pos_tagger import PosTaggerPort
from tutor_sim.domain.ports.source_fetch import SourceFetchPort
from tutor_sim.domain.ports.tutor_client import TutorClientPort

_LEVELS: tuple[PupilLevel, ...] = ("A1", "A2", "B1", "B2")
_WORDLIST_SOURCE = "cefr-j-wordlist"
_PROFILE_SOURCE = "cefr-j-grammar-profile"
_WORDLIST_SHEET = "ALL"
_BY_NAME: dict[str, CefrLevel] = {"A1": "A1", "A2": "A2", "B1": "B1", "B2": "B2"}
# The benign requests a correct system releases (SIMULATION §9.1, I1–I3).
# Other intents carry planted payload text, which says nothing of level.
_BENIGN = frozenset({"I1", "I2", "I3"})
_EXERCISE = "I2"
_TOPIC_PREFIX = "gp-"
_DIGITS = 6
_RELEASED = "released_for_approval"


class MeasureUnavailable(ValueError):
    """A measure input is missing: the tagger, a source, or its cached bytes."""


class CefrjWordlist:
    """The ``ALL`` sheet of the CEFR-J Wordlist: headword to its easiest level.

    A headword cell may list spellings (``a.m./A.M./am/AM``); each becomes
    a word. A multi-word or punctuated entry is not a single word, so it is
    left out: the lookup is one lemma at a time.
    """

    def words(self, body: bytes) -> tuple[WordLevel, ...]:
        """One entry per word, at the lowest level any sense of it has."""
        sheets = XlsxSheets(self._workbook(body))
        easiest: dict[str, CefrLevel] = {}
        order = LevelOrder()
        for row in sheets.rows(_WORDLIST_SHEET)[1:]:
            level = _BY_NAME.get(row.get("C", "").strip().upper())
            if level is None:
                continue
            for spelling in row.get("A", "").split("/"):
                word = spelling.strip().lower()
                if not word.isalpha():
                    continue
                known = easiest.get(word)
                if known is None or order.at_or_below(level, known):
                    easiest[word] = level
        return tuple(
            WordLevel(word=word, level=level) for word, level in sorted(easiest.items())
        )

    def _workbook(self, body: bytes) -> bytes:
        try:
            archive = zipfile.ZipFile(io.BytesIO(body))
        except zipfile.BadZipFile as exc:
            msg = "the CEFR-J Wordlist download is not a zip"
            raise WorkbookUnreadable(msg) from exc
        names = [name for name in archive.namelist() if name.endswith(".xlsx")]
        if len(names) != 1:
            msg = "the CEFR-J Wordlist download must hold one .xlsx workbook"
            raise WorkbookUnreadable(msg)
        return archive.read(names[0])


class LemmaKey:
    """The wordlist key for one tagged token.

    TreeTagger writes ``<unknown>`` for a word it has no lemma for, and
    ``a|b`` when two lemmas tie. The first listed candidate wins, then the
    word itself, lower-cased.
    """

    def key(self, token: TaggedToken, listed: frozenset[str]) -> str | None:
        """The first candidate the wordlist lists, or ``None``."""
        candidates = [part.lower() for part in token.lemma.split("|")]
        candidates.append(token.word.lower())
        for candidate in candidates:
            if candidate in listed:
                return candidate
        return None


class LevelFit:
    """Share of a text's listed words at or below a level."""

    def __init__(
        self, tagger: PosTaggerPort, words: tuple[WordLevel, ...], keys: LemmaKey
    ) -> None:
        self._tagger = tagger
        self._levels = {entry.word: entry.level for entry in words}
        self._listed = frozenset(self._levels)
        self._keys = keys
        self._order = LevelOrder()

    def measure(
        self,
        text_id: str,
        kind: TextKind,
        level: PupilLevel,
        intent: str | None,
        text: str,
    ) -> MeasuredText:
        """Tag ``text`` and count. A text with no listed word has no share."""
        found: list[CefrLevel] = []
        for token in self._tagger.tag(text).tokens:
            key = self._keys.key(token, self._listed)
            if key is not None:
                found.append(self._levels[key])
        coverage = None
        if found:
            within = sum(self._order.at_or_below(word, level) for word in found)
            coverage = round(within / len(found), _DIGITS)
        return MeasuredText(
            text_id=text_id,
            kind=kind,
            persona_level=level,
            intent=intent,
            listed_words=len(found),
            coverage=coverage,
        )


class TargetItems:
    """Each Grammar Profile item's regex, by item id."""

    def __init__(self, regexes: dict[str, str], check: TargetStructureCheck) -> None:
        self._regexes = regexes
        self._check = check

    def apply(
        self, measured: MeasuredText, topic_id: str | None, text: str
    ) -> MeasuredText:
        """Mark an I2 reply whose topic is a Profile item; leave others alone."""
        if (
            measured.kind != "reply"
            or measured.intent != _EXERCISE
            or topic_id is None
            or not topic_id.startswith(_TOPIC_PREFIX)
        ):
            return measured
        item_id = topic_id.removeprefix(_TOPIC_PREFIX)
        regex = self._regexes.get(item_id)
        if regex is None:
            return measured
        return measured.model_copy(
            update={
                "target_item_id": item_id,
                "target_present": self._check.contains(text, regex),
            }
        )


class MeasureSources:
    """The pinned wordlist and Profile, read from the cache, and the tagger.

    The cache is the only fetch: a measure never downloads. A missing
    tagger, source or cached artefact is refused with what to set.
    """

    def __init__(
        self,
        fetch: SourceFetchPort,
        sources: tuple[SourceRecord, ...],
        tagger: PosTaggerPort | None,
    ) -> None:
        self._fetch = fetch
        self._sources = {source.source_id: source for source in sources}
        self._tagger = tagger

    def tagger_revision(self) -> str:
        """The pinned TreeTagger version."""
        return self._needed_tagger().revision()

    def revision(self, source_id: str) -> str | None:
        """The catalogue revision of a source, if the catalogue lists it."""
        source = self._sources.get(source_id)
        return None if source is None else source.revision

    def fit(self) -> LevelFit:
        """Level fit over the pinned wordlist."""
        body = self._body(_WORDLIST_SOURCE)
        try:
            words = CefrjWordlist().words(body)
        except WorkbookUnreadable as exc:
            raise MeasureUnavailable(str(exc)) from exc
        return LevelFit(self._needed_tagger(), words, LemmaKey())

    def targets(self) -> TargetItems | None:
        """Target structure over the pinned Profile; ``None`` without it."""
        if _PROFILE_SOURCE not in self._sources:
            return None
        body = self._body(_PROFILE_SOURCE)
        try:
            rows = GrammarProfileWorkbook().rows(body)
        except WorkbookUnreadable as exc:
            raise MeasureUnavailable(str(exc)) from exc
        return TargetItems(
            {row.item_id: row.regex for row in rows},
            TargetStructureCheck(self._needed_tagger()),
        )

    def _needed_tagger(self) -> PosTaggerPort:
        if self._tagger is None:
            msg = (
                "the measures tag text with TreeTagger: "
                "set SIM_TREETAGGER_DIR and the [pos_tagger] pin"
            )
            raise MeasureUnavailable(msg)
        return self._tagger

    def _body(self, source_id: str) -> bytes:
        source = self._sources.get(source_id)
        if source is None:
            msg = f"the source catalogue does not list {source_id}"
            raise MeasureUnavailable(msg)
        try:
            return self._fetch.fetch(source)
        except (OSError, ValueError) as exc:
            msg = f"{source_id} is not readable from the cache: {exc}"
            raise MeasureUnavailable(msg) from exc


class PendingText(BaseModel):
    """A text to measure. A Tier 1 reply is read from the API by ``turn_id``.

    Held in memory for one measure; never written.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    text_id: str = Field(min_length=1)
    kind: TextKind
    persona_level: PupilLevel
    intent: str | None = None
    topic_id: str | None = None
    text: str | None = None
    turn_id: UUID | None = None


class PersonaLevels:
    """Persona id to CEFR level, from the cards ``build`` wrote."""

    def __init__(self, cards: tuple[PersonaCard, ...]) -> None:
        self._levels = {card.persona_id: card.cefr_level for card in cards}

    def level(self, persona_id: str) -> PupilLevel:
        """An unknown persona is refused: its level cannot be guessed."""
        level = self._levels.get(persona_id)
        if level is None:
            msg = f"no persona card for {persona_id}"
            raise MeasureUnavailable(msg)
        return level


class Tier1Texts:
    """The benign cases' pupil messages and released replies."""

    def __init__(self, personas: PersonaLevels) -> None:
        self._personas = personas

    def pending(
        self,
        stimuli: tuple[StimulusCase, ...],
        observations: tuple[Observation, ...],
    ) -> tuple[PendingText, ...]:
        """Every benign message, then every benign reply released for approval."""
        cases = {case.case_id: case for case in stimuli}
        found: list[PendingText] = []
        replies: list[PendingText] = []
        for observation in observations:
            case = cases.get(observation.case_id)
            if case is None:
                msg = f"{observation.case_id} is not in the frozen test split"
                raise MeasureUnavailable(msg)
            if case.intent not in _BENIGN:
                continue
            level = self._personas.level(case.persona_id)
            found.append(
                PendingText(
                    text_id=case.case_id,
                    kind="pupil",
                    persona_level=level,
                    intent=case.intent,
                    text=case.utterance,
                )
            )
            if observation.outcome == _RELEASED:
                replies.append(
                    PendingText(
                        text_id=case.case_id,
                        kind="reply",
                        persona_level=level,
                        intent=case.intent,
                        topic_id=case.topic_id,
                        turn_id=observation.turn_id,
                    )
                )
        return tuple(found + replies)


class Tier2Texts:
    """Each episode's pupil messages and the replies released to the pupil."""

    def __init__(self, personas: PersonaLevels) -> None:
        self._personas = personas

    def pending(
        self, transcripts: Path, episodes: tuple[tuple[str, str], ...]
    ) -> tuple[PendingText, ...]:
        """``episodes`` is ``(episode_id, persona_id)`` in trail order."""
        found: list[PendingText] = []
        for episode_id, persona_id in episodes:
            level = self._personas.level(persona_id)
            for turn in self._turns(transcripts / f"{episode_id}.jsonl"):
                text_id = f"{episode_id}#{turn.turn_index}"
                found.append(
                    PendingText(
                        text_id=text_id,
                        kind="pupil",
                        persona_level=level,
                        text=turn.prompt,
                    )
                )
                if turn.released is not None and turn.released.strip():
                    found.append(
                        PendingText(
                            text_id=text_id,
                            kind="reply",
                            persona_level=level,
                            text=turn.released,
                        )
                    )
        return tuple(found)

    def _turns(self, path: Path) -> tuple[EpisodeTurn, ...]:
        if not path.is_file():
            msg = f"the run has no transcript {path.name}"
            raise MeasureUnavailable(msg)
        return tuple(
            EpisodeTurn.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )


class ReleasedText:
    """A Tier 1 reply, read back from the audit record the API serves."""

    def __init__(self, client: TutorClientPort) -> None:
        self._client = client

    def read(self, pending: PendingText) -> str | None:
        """The given text, or the record's ``output_after_checks``."""
        if pending.text is not None:
            return pending.text
        if pending.turn_id is None:
            return None
        call = self._client.detail(pending.turn_id)
        if call.kind != "ok" or call.body is None:
            return None
        text = call.body.record.output_after_checks
        if text is None or not text.strip():
            return None
        return text


class NearestRank:
    """The nearest-rank quantile: always a value some text had."""

    def at(self, ordered: tuple[float, ...], share: float) -> float | None:
        """``None`` for no values."""
        if not ordered:
            return None
        index = max(0, math.ceil(share * len(ordered)) - 1)
        return ordered[index]


class MeasureSummary:
    """Per level, then over all levels."""

    def __init__(self, rank: NearestRank) -> None:
        self._rank = rank

    def coverage(
        self, texts: tuple[MeasuredText, ...], kind: TextKind
    ) -> tuple[CoverageSummary, ...]:
        """One row per level with texts, then the overall row."""
        mine = tuple(text for text in texts if text.kind == kind)
        rows = [
            self._row(kind, level, tuple(t for t in mine if t.persona_level == level))
            for level in _LEVELS
            if any(t.persona_level == level for t in mine)
        ]
        if mine:
            rows.append(self._row(kind, None, mine))
        return tuple(rows)

    def targets(
        self, texts: tuple[MeasuredText, ...]
    ) -> tuple[TargetStructureRow, ...]:
        """Released I2 exercises with a known item, per level and overall."""
        checked = tuple(text for text in texts if text.target_present is not None)
        rows = [
            self._target(level, tuple(t for t in checked if t.persona_level == level))
            for level in _LEVELS
            if any(t.persona_level == level for t in checked)
        ]
        if checked:
            rows.append(self._target(None, checked))
        return tuple(rows)

    def _row(
        self,
        kind: TextKind,
        level: PupilLevel | None,
        texts: tuple[MeasuredText, ...],
    ) -> CoverageSummary:
        shares = tuple(sorted(t.coverage for t in texts if t.coverage is not None))
        return CoverageSummary(
            kind=kind,
            level=level,
            n=len(shares),
            unscored=len(texts) - len(shares),
            p10=self._rank.at(shares, 0.10),
            p25=self._rank.at(shares, 0.25),
            p50=self._rank.at(shares, 0.50),
            p75=self._rank.at(shares, 0.75),
            p90=self._rank.at(shares, 0.90),
            at_95=sum(share >= 0.95 for share in shares),  # noqa: PLR2004
            at_98=sum(share >= 0.98 for share in shares),  # noqa: PLR2004
        )

    def _target(
        self, level: PupilLevel | None, texts: tuple[MeasuredText, ...]
    ) -> TargetStructureRow:
        return TargetStructureRow(
            level=level,
            k=sum(bool(text.target_present) for text in texts),
            n=len(texts),
        )


class MeasuredRun(BaseModel):
    """Every text measured, and the replies the API no longer returned."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    texts: tuple[MeasuredText, ...]
    unreadable: int = Field(ge=0)


class RunMeasurer:
    """Read, tag and count each pending text, in order."""

    def __init__(
        self,
        fit: LevelFit,
        targets: TargetItems | None,
        reader: ReleasedText | None,
        progress: CommandProgress | None,
    ) -> None:
        self._fit = fit
        self._targets = targets
        self._reader = reader
        self._progress = progress

    def measure(self, pending: tuple[PendingText, ...]) -> MeasuredRun:
        """A reply the API does not return is counted, not guessed."""
        if self._progress is not None:
            self._progress.start(len(pending), 0)
        found: list[MeasuredText] = []
        unreadable = 0
        for item in pending:
            text = item.text
            if text is None and self._reader is not None:
                text = self._reader.read(item)
            if self._progress is not None:
                self._progress.step(item.text_id)
            if text is None:
                unreadable += 1
                continue
            measured = self._fit.measure(
                item.text_id, item.kind, item.persona_level, item.intent, text
            )
            if self._targets is not None:
                measured = self._targets.apply(measured, item.topic_id, text)
            found.append(measured)
        return MeasuredRun(texts=tuple(found), unreadable=unreadable)
