"""Contracts C1–C4. The committed schema is the agreement across packages."""

import json

from tests.support.repository import RepositoryPaths

from tutor_core.domain.models.corpus import CorpusDocument
from tutor_core.domain.models.simulation import SimulationReport as ReadReport
from tutor_core.domain.models.simulation import SimulationRunSummary
from tutor_sim.domain.models.kb import KbDocumentRecord
from tutor_sim.domain.models.learner import PersonaLearnerRecord
from tutor_sim.domain.models.report import RunSummary, SimulationReport


class SchemaFile:
    def load(self, name: str) -> dict[str, object]:
        path = RepositoryPaths().root() / "docs" / "evaluation" / "schemas" / name
        return json.loads(path.read_text(encoding="utf-8"))


class Shape:
    """A schema without titles and descriptions: the fields both sides agree on."""

    def of(self, schema: object) -> object:
        if isinstance(schema, dict):
            return {
                key: self.of(value)
                for key, value in schema.items()
                if key not in {"title", "description"}
            }
        if isinstance(schema, list):
            return [self.of(item) for item in schema]
        return schema


class TestCrossPackageSchemas:
    def test_kb_document_matches_the_committed_schema(self) -> None:
        assert SchemaFile().load("kb-document.schema.json") == (
            KbDocumentRecord.model_json_schema()
        )

    def test_persona_learner_matches_the_committed_schema(self) -> None:
        assert SchemaFile().load("persona-learner.schema.json") == (
            PersonaLearnerRecord.model_json_schema()
        )

    def test_simulation_report_matches_the_committed_schema(self) -> None:
        schema = SchemaFile().load("simulation-report.schema.json")
        assert schema == SimulationReport.model_json_schema()
        assert schema == ReadReport.model_json_schema()

    def test_run_summary_matches_the_committed_schema(self) -> None:
        assert SchemaFile().load("simulation-run-summary.schema.json") == (
            RunSummary.model_json_schema()
        )

    def test_the_api_reads_the_report_in_the_committed_shape(self) -> None:
        committed = SchemaFile().load("simulation-report.schema.json")
        assert Shape().of(committed) == Shape().of(ReadReport.model_json_schema())

    def test_the_api_reads_the_summary_in_the_committed_shape(self) -> None:
        committed = SchemaFile().load("simulation-run-summary.schema.json")
        assert Shape().of(committed) == Shape().of(
            SimulationRunSummary.model_json_schema()
        )

    def test_corpus_document_shares_the_provenance_fields(self) -> None:
        kb = KbDocumentRecord.model_json_schema()
        core = CorpusDocument.model_json_schema()
        for name in ("licence", "cefr_level", "level_method"):
            assert core["properties"][name] == kb["properties"][name]
            assert name in core["required"]
