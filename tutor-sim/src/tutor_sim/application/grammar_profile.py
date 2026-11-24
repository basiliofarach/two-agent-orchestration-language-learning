"""Read the CEFR-J Grammar Profile download (DATASET §3.1).

The download is a zip holding one ``.xlsx`` workbook. A workbook is itself
a zip of XML parts, so the standard library reads it: no spreadsheet
dependency. Two sheets are used. The teachers' sheet (``教員版``) lists
256 items and the CEFR-J level each is taught at. ``ITEM LIST`` gives
each item's pattern shorthand and its TreeTagger-based regex.

The bytes reaching this module are the catalogue's pinned artefact: the
fetch checks the sha256 before returning them.
"""

import io
import re
import zipfile
from xml.etree import ElementTree

from tutor_sim.domain.models.grammar import GrammarProfileRow

_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
_PKG = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_TEACHERS = "教員版"
_ITEMS = "ITEM LIST"
_HEADER_ROWS = 2


class WorkbookUnreadable(ValueError):
    """The download is not the workbook the build expects."""


class PerlRegex:
    """Rewrite the Profile's Perl regexes for Python's ``re``.

    The build asks one question of a regex: does the tagged sentence
    contain the item? Each rewrite keeps that answer.

    * ``\\K`` only moves where a match starts. It is dropped.
    * ``(?<name>…)`` is a named group; Python spells it ``(?P<name>…)``.
      ``(?<=`` and ``(?<!`` are lookbehinds and stay as they are.
    * ``\\g{name}`` is a backreference; Python spells it ``(?P=name)``.
    """

    def translate(self, pattern: str) -> str:
        """The same pattern in Python syntax."""
        rewritten = pattern.replace("\\K", "")
        rewritten = re.sub(r"\(\?<(?![=!])", "(?P<", rewritten)
        return re.sub(r"\\g\{(\w+)\}", r"(?P=\1)", rewritten)


class XlsxSheets:
    """Cell text of a workbook's sheets, by sheet name and column letter."""

    def __init__(self, workbook: bytes) -> None:
        try:
            self._zip = zipfile.ZipFile(io.BytesIO(workbook))
            self._shared = self._strings()
            self._paths = self._sheet_paths()
        except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as exc:
            msg = "the Grammar Profile workbook is not a readable .xlsx"
            raise WorkbookUnreadable(msg) from exc

    def rows(self, name: str) -> tuple[dict[str, str], ...]:
        """Every row of sheet ``name``: column letter to text. Blank is ``""``."""
        path = self._paths.get(name)
        if path is None:
            msg = f"the Grammar Profile workbook has no sheet named {name}"
            raise WorkbookUnreadable(msg)
        root = self._xml(path)
        data = root.find(f"{_MAIN}sheetData")
        found: list[dict[str, str]] = []
        for row in () if data is None else data:
            cells: dict[str, str] = {}
            for cell in row:
                column = "".join(ch for ch in cell.get("r", "") if ch.isalpha())
                cells[column] = self._value(cell)
            found.append(cells)
        return tuple(found)

    def _value(self, cell: ElementTree.Element) -> str:
        kind = cell.get("t")
        if kind == "inlineStr":
            inline = cell.find(f"{_MAIN}is")
            return "" if inline is None else self._text(inline)
        value = cell.find(f"{_MAIN}v")
        if value is None or value.text is None:
            return ""
        if kind == "s":
            return self._shared[int(value.text)]
        return value.text

    def _strings(self) -> tuple[str, ...]:
        if "xl/sharedStrings.xml" not in self._zip.namelist():
            return ()
        root = self._xml("xl/sharedStrings.xml")
        return tuple(self._text(item) for item in root.findall(f"{_MAIN}si"))

    def _text(self, item: ElementTree.Element) -> str:
        """Plain and rich-text runs. Phonetic readings (``rPh``) are not text."""
        direct = "".join(t.text or "" for t in item.findall(f"{_MAIN}t"))
        runs = "".join(
            t.text or ""
            for run in item.findall(f"{_MAIN}r")
            for t in run.findall(f"{_MAIN}t")
        )
        return direct + runs

    def _sheet_paths(self) -> dict[str, str]:
        targets = {
            rel.get("Id", ""): rel.get("Target", "")
            for rel in self._xml("xl/_rels/workbook.xml.rels").findall(
                f"{_PKG}Relationship"
            )
        }
        sheets = self._xml("xl/workbook.xml").find(f"{_MAIN}sheets")
        paths: dict[str, str] = {}
        for sheet in () if sheets is None else sheets:
            target = targets[sheet.get(_REL, "")].lstrip("/")
            paths[sheet.get("name", "")] = (
                target if target.startswith("xl/") else f"xl/{target}"
            )
        return paths

    def _xml(self, path: str) -> ElementTree.Element:
        # The pinned artefact's own parts; expat resolves no external entities.
        return ElementTree.fromstring(self._zip.read(path))  # noqa: S314


class GrammarProfileWorkbook:
    """One row per teachers' item, joined to its regex in ``ITEM LIST``."""

    def __init__(self) -> None:
        self._regex = PerlRegex()

    def workbook(self, body: bytes) -> bytes:
        """The single ``.xlsx`` inside the download."""
        try:
            archive = zipfile.ZipFile(io.BytesIO(body))
        except zipfile.BadZipFile as exc:
            msg = "the Grammar Profile download is not a zip"
            raise WorkbookUnreadable(msg) from exc
        names = [name for name in archive.namelist() if name.endswith(".xlsx")]
        if len(names) != 1:
            msg = "the Grammar Profile download must hold one .xlsx workbook"
            raise WorkbookUnreadable(msg)
        return archive.read(names[0])

    def rows(self, body: bytes) -> tuple[GrammarProfileRow, ...]:
        """Teachers' items in sheet order. An item without a regex is refused."""
        sheets = XlsxSheets(self.workbook(body))
        listed = {
            row.get("A", "").strip(): row
            for row in sheets.rows(_ITEMS)[_HEADER_ROWS:]
            if row.get("A", "").strip()
        }
        found: list[GrammarProfileRow] = []
        for row in sheets.rows(_TEACHERS)[_HEADER_ROWS:]:
            item_id = row.get("A", "").strip()
            if not item_id:
                continue
            item = listed.get(item_id)
            if item is None or not item.get("I", "").strip():
                msg = f"teachers' item {item_id} has no regex in {_ITEMS}"
                raise WorkbookUnreadable(msg)
            found.append(
                GrammarProfileRow(
                    item_id=item_id,
                    name=(item.get("E") or row.get("D", "")).strip(),
                    cefr_j_level=row.get("E", "").strip(),
                    pattern=item.get("H", "").strip() or item_id,
                    regex=self._regex.translate(item["I"].strip()),
                )
            )
        return tuple(found)
