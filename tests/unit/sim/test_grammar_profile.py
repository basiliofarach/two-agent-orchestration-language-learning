"""The CEFR-J Grammar Profile into the knowledge base.

The teachers' sheet names 256 items and the CEFR-J level each is taught
at. ``ITEM LIST`` holds each item's TreeTagger-based regex, written for
Perl: ``\\K``, ``(?<name>…)`` and ``\\g{name}``. Python's ``re`` has none of
them, so each is rewritten to a form with the same yes/no answer.
"""

import re

import pytest
from tests.support.grammar_workbook import ITEMS, WordTagger, WorkbookFixture
from tests.unit.sim.test_build import FixtureFetch, MemoryStore, Sources

from tutor_sim.application.build import BuildFailure, DatasetBuild, KbTopics
from tutor_sim.application.grammar_profile import (
    GrammarProfileWorkbook,
    PerlRegex,
    WorkbookUnreadable,
    XlsxSheets,
)
from tutor_sim.application.kb_corpus import GrammarProfileLoader, KbCorpusBuilder
from tutor_sim.application.realise import PlanFile
from tutor_sim.domain.models.grammar import GrammarItem, GrammarProfileRow
from tutor_sim.domain.models.identity import SimulationNamespace
from tutor_sim.domain.models.kb import KbDocumentRecord


class TestPerlRegex:
    def test_keep_out_is_dropped_because_it_moves_only_the_match_start(self) -> None:
        assert PerlRegex().translate(r"a_DT_a \Kfish_NN_fish") == r"a_DT_a fish_NN_fish"

    def test_a_named_group_and_its_backreference_use_python_syntax(self) -> None:
        translated = PerlRegex().translate(r"(?<prep>in|on)_IN_\g{prep}\b")
        assert translated == r"(?P<prep>in|on)_IN_(?P=prep)\b"
        assert re.search(translated, "in_IN_in rest")
        assert not re.search(translated, "in_IN_on rest")

    def test_lookbehinds_are_left_alone(self) -> None:
        assert PerlRegex().translate(r"(?<=x)(?<!y)z") == r"(?<=x)(?<!y)z"

    def test_every_fixture_regex_compiles_after_translation(self) -> None:
        for _id, _name, _level, _pattern, regex in ITEMS:
            re.compile(PerlRegex().translate(regex))


class TestXlsxSheets:
    def test_sheets_are_read_by_name_without_phonetic_readings(self) -> None:
        sheets = XlsxSheets(GrammarProfileWorkbook().workbook(WorkbookFixture().body()))
        header = sheets.rows("ITEM LIST")[1]
        assert header["B"] == "文法項目"
        assert sheets.rows("教員版")[2] == {
            "A": "13",
            "B": "",
            "C": "",
            "D": "INDEFINITE ARTICLES",
            "E": "A1.1",
        }

    def test_a_missing_sheet_is_refused(self) -> None:
        sheets = XlsxSheets(GrammarProfileWorkbook().workbook(WorkbookFixture().body()))
        with pytest.raises(WorkbookUnreadable, match="no sheet named Nope"):
            sheets.rows("Nope")


class TestGrammarProfileWorkbook:
    def test_each_teachers_item_is_joined_to_its_regex(self) -> None:
        rows = GrammarProfileWorkbook().rows(WorkbookFixture().body())
        assert rows[0] == GrammarProfileRow(
            item_id="13",
            name="INDEFINITE ARTICLES",
            cefr_j_level="A1.1",
            pattern="(a|an)",
            regex=r"\b(a|an)_DT_(a|an)\b",
        )
        assert [row.item_id for row in rows] == ["13", "58", "21"]
        assert rows[2].regex == r"(?P<prep>in|on)_IN_(?P=prep)\b"

    def test_a_teachers_item_missing_from_the_item_list_is_refused(self) -> None:
        body = WorkbookFixture().body(extra_teacher_ids=("999",))
        with pytest.raises(WorkbookUnreadable, match="999"):
            GrammarProfileWorkbook().rows(body)

    def test_a_download_without_the_teachers_sheet_is_refused(self) -> None:
        body = WorkbookFixture().body(teachers_sheet="Other")
        with pytest.raises(WorkbookUnreadable, match="教員版"):
            GrammarProfileWorkbook().rows(body)

    def test_a_download_without_a_workbook_is_refused(self) -> None:
        import io
        import zipfile

        empty = io.BytesIO()
        with zipfile.ZipFile(empty, "w") as archive:
            archive.writestr("README.txt", "no workbook")
        with pytest.raises(WorkbookUnreadable, match="one .xlsx"):
            GrammarProfileWorkbook().rows(empty.getvalue())


class TestLevelRanges:
    def test_a_level_range_is_taught_from_its_first_level(self) -> None:
        rows = GrammarProfileWorkbook().rows(WorkbookFixture().body())
        items = GrammarProfileLoader().load(rows)
        assert [(item.cefr_j_level, item.band) for item in items] == [
            ("A1.1", "A1"),
            ("A1.1-A1.2", "A1"),
            ("A2.2-B1.1", "A2"),
        ]

    def test_an_unknown_level_in_a_range_is_refused(self) -> None:
        row = GrammarProfileWorkbook().rows(WorkbookFixture().body())[0]
        with pytest.raises(ValueError, match="C1.1"):
            GrammarProfileLoader().load(
                (row.model_copy(update={"cefr_j_level": "C1.1-C2"}),)
            )


def _item(pattern: str) -> GrammarItem:
    return GrammarItem(
        item_id="13",
        name="INDEFINITE ARTICLES",
        cefr_j_level="A1.1",
        band="A1",
        pattern=pattern,
        regex=r"\b(a|an)_DT_(a|an)\b",
    )


class TestGrammarDocuments:
    def _document(self, pattern: str) -> KbDocumentRecord:
        builder = KbCorpusBuilder(SimulationNamespace(), "custom:permission-by-email")
        return builder.build((), (_item(pattern),), ())[0]

    def test_the_document_carries_the_catalogue_licence(self) -> None:
        assert self._document("(a|an)").licence == "custom:permission-by-email"

    def test_an_english_pattern_is_kept_and_a_japanese_one_left_out(self) -> None:
        assert "Pattern: (a|an)" in self._document("(a|an)").content
        assert "Pattern" not in self._document("名詞句 \\K VB[PZ]").content
        assert "INDEFINITE ARTICLES" in self._document("名詞句").content


def _documents(*specs: tuple[str, str, str]) -> tuple[KbDocumentRecord, ...]:
    builder = KbCorpusBuilder(SimulationNamespace(), "custom:x")
    items = tuple(
        _item("(a|an)").model_copy(update={"item_id": i, "band": band})
        for i, band, _kind in specs
        if _kind == "grammar"
    )
    return builder.build((), items, ())


class TestKbTopics:
    def test_grammar_items_are_the_topics_where_a_level_has_them(self) -> None:
        documents = _documents(("13", "A1", "grammar"), ("21", "A2", "grammar"))
        sentences = tuple(
            KbDocumentRecord.model_validate(
                {
                    **documents[0].model_dump(),
                    "document_id": SimulationNamespace().learner_id(f"s-{level}"),
                    "source_uri": f"kb://cefr-sp/score/{level}",
                    "topic_id": f"cefr-sp-score-{level}",
                    "cefr_level": level,
                }
            )
            for level in ("A1", "A2", "B1", "B2")
        )
        topics = KbTopics().by_level(documents + sentences)
        assert topics["A1"] == ("gp-13",)
        assert topics["A2"] == ("gp-21",)
        assert topics["B1"] == ("cefr-sp-score-B1",)

    def test_a_level_with_no_document_at_all_fails(self) -> None:
        with pytest.raises(BuildFailure, match="no A2 document"):
            KbTopics().by_level(_documents(("13", "A1", "grammar")))


class TestBuildWithTheProfile:
    def _sources(self, tmp_path):  # type: ignore[no-untyped-def]
        records, bodies = Sources().all(tmp_path / "public" / "authored")
        body = WorkbookFixture().body()
        profile = Sources().record(
            "cefr-j-grammar-profile", body, redistributable=False
        )
        return records + (profile,), {**bodies, "cefr-j-grammar-profile": body}

    def test_the_profile_needs_a_tagger(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        records, bodies = self._sources(tmp_path)
        build = DatasetBuild(FixtureFetch(bodies), MemoryStore(), records, tmp_path, 7)
        with pytest.raises(BuildFailure, match="TreeTagger"):
            build.run()

    def test_grammar_items_become_documents_and_topics(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        import json

        records, bodies = self._sources(tmp_path)
        store = MemoryStore()
        DatasetBuild(
            FixtureFetch(bodies), store, records, tmp_path, 7, WordTagger()
        ).run()
        documents = [
            json.loads(line)
            for line in store.files[("restricted", "kb/documents.jsonl")].splitlines()
        ]
        grammar = [
            d
            for d in documents
            if d["source_uri"].startswith("kb://cefr-j-grammar-profile/")
        ]
        assert {d["topic_id"] for d in grammar} == {"gp-13", "gp-58", "gp-21"}
        article = next(d for d in grammar if d["topic_id"] == "gp-13")
        assert "I have a fish ." in article["content"]
        assert article["licence"].startswith("custom:non-commercial")
        plan = PlanFile().load(tmp_path / "plan.json")
        a1 = {
            case.topic_id for case in plan.cases if case.persona_id.startswith("p-a1")
        }
        assert "gp-13" in a1

    def test_a_build_without_the_profile_needs_no_tagger(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        records, bodies = Sources().all(tmp_path / "public" / "authored")
        DatasetBuild(FixtureFetch(bodies), MemoryStore(), records, tmp_path, 7).run()


class MinimalXlsx:
    """One sheet, no shared strings, every cell kind the reader handles."""

    def body(self) -> bytes:
        import io
        import zipfile

        main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        rels = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        pkg = "http://schemas.openxmlformats.org/package/2006/relationships"
        sheet = (
            f'<worksheet xmlns="{main}"><sheetData><row r="1">'
            '<c r="A1" t="inlineStr"><is><t>inline</t></is></c>'
            '<c r="B1" t="inlineStr"/>'
            '<c r="C1"/>'
            '<c r="D1"><v>42</v></c>'
            "</row></sheetData></worksheet>"
        )
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as book:
            book.writestr(
                "xl/workbook.xml",
                f'<workbook xmlns="{main}" xmlns:r="{rels}"><sheets>'
                '<sheet name="Only" sheetId="1" r:id="rId1"/></sheets></workbook>',
            )
            book.writestr(
                "xl/_rels/workbook.xml.rels",
                f'<Relationships xmlns="{pkg}"><Relationship Id="rId1" '
                'Target="/xl/worksheets/sheet1.xml" Type="worksheet"/>'
                "</Relationships>",
            )
            book.writestr("xl/worksheets/sheet1.xml", sheet)
        return buffer.getvalue()


class TestUnusualWorkbooks:
    def test_inline_empty_and_numeric_cells_without_shared_strings(self) -> None:
        rows = XlsxSheets(MinimalXlsx().body()).rows("Only")
        assert rows == ({"A": "inline", "B": "", "C": "", "D": "42"},)

    def test_bytes_that_are_not_a_workbook_are_refused(self) -> None:
        with pytest.raises(WorkbookUnreadable, match="not a readable .xlsx"):
            XlsxSheets(b"not a workbook")

    def test_a_download_that_is_not_a_zip_is_refused(self) -> None:
        with pytest.raises(WorkbookUnreadable, match="not a zip"):
            GrammarProfileWorkbook().rows(b"not a zip")

    def test_a_teachers_row_without_an_id_is_skipped(self) -> None:
        rows = GrammarProfileWorkbook().rows(
            WorkbookFixture().body(extra_teacher_ids=("",))
        )
        assert [row.item_id for row in rows] == ["13", "58", "21"]

    def test_an_unreadable_profile_fails_the_build(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        records, bodies = Sources().all(tmp_path / "public" / "authored")
        profile = Sources().record("cefr-j-grammar-profile", b"junk", False)
        build = DatasetBuild(
            FixtureFetch({**bodies, "cefr-j-grammar-profile": b"junk"}),
            MemoryStore(),
            (*records, profile),
            tmp_path,
            7,
            WordTagger(),
        )
        with pytest.raises(BuildFailure, match="not a zip"):
            build.run()
