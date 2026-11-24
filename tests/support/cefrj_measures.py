"""A small CEFR-J Wordlist download and the two sources the measures read.

The wordlist is a zip holding one ``.xlsx`` with the ``ALL`` sheet laid out
like the real file: a header row, then ``headword | pos | CEFR``. The fetch
serves it and the Grammar Profile fixture by source id, as the cache would.
"""

import io
import zipfile

from tests.support.grammar_workbook import WorkbookFixture
from tests.unit.sim.test_kernel import PinnedSource
from tutor_sim.domain.models.source import SourceRecord
from tutor_sim.domain.ports.source_fetch import SourceFetchPort

WORDS: tuple[tuple[str, str, str], ...] = (
    ("a", "determiner", "A1"),
    ("a.m./A.M./am/AM", "adverb", "A1"),
    ("cat", "noun", "A1"),
    ("give", "verb", "A1"),
    ("I", "pronoun", "A1"),
    ("me", "pronoun", "A1"),
    ("play", "verb", "A1"),
    ("play", "noun", "A2"),
    ("wish", "verb", "B1"),
    ("hypothesis", "noun", "B2"),
    ("run out", "verb", "B1"),
)


class WordlistFixture(WorkbookFixture):
    """Build the CEFR-J Wordlist zip: one workbook, an ``ALL`` sheet."""

    def wordlist(self, words: tuple[tuple[str, str, str], ...] = WORDS) -> bytes:
        strings: list[str] = []
        rows = [["headword", "pos", "CEFR"], *[list(word) for word in words]]
        sheets = {"README": self._sheet([["readme"]], strings)}
        sheets["ALL"] = self._sheet(rows, strings)
        xlsx = io.BytesIO()
        with zipfile.ZipFile(xlsx, "w") as book:
            book.writestr("xl/workbook.xml", self._workbook(tuple(sheets)))
            book.writestr("xl/_rels/workbook.xml.rels", self._rels(len(sheets)))
            book.writestr("xl/sharedStrings.xml", self._shared(strings))
            for index, xml in enumerate(sheets.values(), start=1):
                book.writestr(f"xl/worksheets/sheet{index}.xml", xml)
        outer = io.BytesIO()
        with zipfile.ZipFile(outer, "w") as archive:
            archive.writestr("CEFR-J Wordlist Ver1.6.xlsx", xlsx.getvalue())
        return outer.getvalue()


class CefrjSources:
    """Catalogue records for the wordlist and the Profile."""

    def records(self, profile: bool = True) -> tuple[SourceRecord, ...]:
        base = PinnedSource().record()
        wordlist = base.model_copy(
            update={"source_id": "cefr-j-wordlist", "revision": "1.6"}
        )
        if not profile:
            return (wordlist,)
        grammar = base.model_copy(
            update={"source_id": "cefr-j-grammar-profile", "revision": "2025-02-25"}
        )
        return (wordlist, grammar)


class CefrjFetch(SourceFetchPort):
    """Serve each fixture by source id. An unknown id is a cache miss."""

    def __init__(self) -> None:
        self.bodies = {
            "cefr-j-wordlist": WordlistFixture().wordlist(),
            "cefr-j-grammar-profile": WorkbookFixture().body(),
        }

    def fetch(self, source: SourceRecord) -> bytes:
        body = self.bodies.get(source.source_id)
        if body is None:
            msg = f"{source.source_id} is not in the cache"
            raise FileNotFoundError(msg)
        return body
