"""A small Grammar Profile download: a zip holding one ``.xlsx`` workbook.

The workbook has the two sheets the build reads, ``ITEM LIST`` and the
teachers' sheet ``教員版``, laid out like the real file: a title row, a
header row, then one row per item. One shared string carries a Japanese
reading (``rPh``), which a reader must not mix into the cell text.
"""

import io
import zipfile
from xml.sax.saxutils import escape

from tutor_sim.domain.models.grammar import TaggedSentence, TaggedToken
from tutor_sim.domain.ports.pos_tagger import PosTaggerPort

_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_RELS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"

ITEMS: tuple[tuple[str, str, str, str, str], ...] = (
    # id, English item, teachers' level, pattern shorthand, TreeTagger regex
    ("13", "INDEFINITE ARTICLES", "A1.1", "(a|an)", r"\b(a|an)_DT_(a|an)\b"),
    (
        "58",
        "TENSE/ASPECT: PRESENT (BE)",
        "A1.1-A1.2",
        "名詞句 \\K VB[PZ]",
        r"\S+_N..?_\S+ \K\S+_VB[PZ]_be",
    ),
    (
        "21",
        "PREPOSITIONS",
        "A2.2-B1.1",
        "前置詞",
        r"(?<prep>in|on)_IN_\g{prep}\b",
    ),
)


class WorkbookFixture:
    """Build the zip the catalogue's sha256 names."""

    def body(
        self,
        items: tuple[tuple[str, str, str, str, str], ...] = ITEMS,
        teachers_sheet: str = "教員版",
        extra_teacher_ids: tuple[str, ...] = (),
    ) -> bytes:
        strings: list[str] = []
        item_rows = [
            ["Grammatical Item List version: 20200220"],
            [
                "ID",
                "文法項目",
                "",
                "Shorthand Code",
                "Grammatical Item",
                "",
                "",
                "パターン略記",
                "正規表現",
            ],
            *[
                [i, "", "", "", name, "", "", pattern, regex]
                for i, name, _l, pattern, regex in items
            ],
        ]
        teacher_rows = [
            ["CEFR-J Grammar Profile for Teachers"],
            ["ID", "文法項目", "", "Grammatical item (English)", "CEFR-J level"],
            *[[i, "", "", name, level] for i, name, level, _p, _r in items],
            *[[i, "", "", "UNKNOWN", "A1.1"] for i in extra_teacher_ids],
        ]
        sheets = {
            "ITEM LIST": self._sheet(item_rows, strings),
            teachers_sheet: self._sheet(teacher_rows, strings),
        }
        xlsx = io.BytesIO()
        with zipfile.ZipFile(xlsx, "w") as book:
            book.writestr("xl/workbook.xml", self._workbook(tuple(sheets)))
            book.writestr("xl/_rels/workbook.xml.rels", self._rels(len(sheets)))
            book.writestr("xl/sharedStrings.xml", self._shared(strings))
            for index, xml in enumerate(sheets.values(), start=1):
                book.writestr(f"xl/worksheets/sheet{index}.xml", xml)
        outer = io.BytesIO()
        with zipfile.ZipFile(outer, "w") as archive:
            archive.writestr("README.txt", "fixture")
            archive.writestr("CEFR-J Grammar Profile.xlsx", xlsx.getvalue())
        return outer.getvalue()

    def _sheet(self, rows: list[list[str]], strings: list[str]) -> str:
        lines = []
        for number, row in enumerate(rows, start=1):
            cells = []
            for column, value in enumerate(row):
                ref = f"{chr(ord('A') + column)}{number}"
                if value.isdigit():
                    cells.append(f'<c r="{ref}"><v>{value}</v></c>')
                    continue
                strings.append(value)
                cells.append(f'<c r="{ref}" t="s"><v>{len(strings) - 1}</v></c>')
            lines.append(f'<row r="{number}">{"".join(cells)}</row>')
        return (
            f'<worksheet xmlns="{_MAIN}"><sheetData>{"".join(lines)}</sheetData>'
            "</worksheet>"
        )

    def _shared(self, strings: list[str]) -> str:
        items = []
        for text in strings:
            if text == "文法項目":
                # A run plus a phonetic reading: only the run is cell text.
                items.append(
                    f"<si><r><t>{escape(text)}</t></r>"
                    '<rPh sb="0" eb="4"><t>ブンポウコウモク</t></rPh></si>'
                )
                continue
            items.append(f'<si><t xml:space="preserve">{escape(text)}</t></si>')
        return f'<sst xmlns="{_MAIN}">{"".join(items)}</sst>'

    def _workbook(self, names: tuple[str, ...]) -> str:
        sheets = "".join(
            f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>'
            for i, name in enumerate(names, start=1)
        )
        return (
            f'<workbook xmlns="{_MAIN}" xmlns:r="{_RELS}"><sheets>{sheets}</sheets>'
            "</workbook>"
        )

    def _rels(self, count: int) -> str:
        rels = "".join(
            f'<Relationship Id="rId{i}" Target="worksheets/sheet{i}.xml" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/worksheet"/>'
            for i in range(1, count + 1)
        )
        return f'<Relationships xmlns="{_PKG}">{rels}</Relationships>'


class WordTagger(PosTaggerPort):
    """Tag by a small word list; anything else is ``NN``. Not TreeTagger."""

    _TAGS = {
        "a": "DT",
        "an": "DT",
        "the": "DT",
        "is": "VBZ",
        "are": "VBP",
        "in": "IN",
        "on": "IN",
        ".": "SENT",
    }

    def revision(self) -> str:
        return "word-tagger-fixture"

    def tag(self, sentence: str) -> TaggedSentence:
        tokens = tuple(
            TaggedToken(
                word=word,
                tag=self._TAGS.get(word.lower(), "NN"),
                lemma="be" if word.lower() in {"is", "are"} else word.lower(),
            )
            for word in sentence.split()
        )
        return TaggedSentence(text=sentence, tokens=tokens)
