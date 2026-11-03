"""Contracts C1–C3. The committed schema is the agreement across packages."""

import json

from tests.support.repository import RepositoryPaths

from tutor_core.domain.models.corpus import CorpusDocument
from tutor_sim.domain.models.kb import KbDocumentRecord
from tutor_sim.domain.models.learner import PersonaLearnerRecord
from tutor_sim.domain.models.report import SimulationReport


class SchemaFile:
    def load(self, name: str) -> dict[str, object]:
        path = RepositoryPaths().root() / "docs" / "evaluation" / "schemas" / name
        return json.loads(path.read_text(encoding="utf-8"))


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
        assert SchemaFile().load("simulation-report.schema.json") == (
            SimulationReport.model_json_schema()
        )

    def test_corpus_document_shares_the_provenance_fields(self) -> None:
        kb = KbDocumentRecord.model_json_schema()
        core = CorpusDocument.model_json_schema()
        for name in ("licence", "cefr_level", "level_method"):
            assert core["properties"][name] == kb["properties"][name]
            assert name in core["required"]
