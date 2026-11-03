"""A fresh database migrates, seeds, and a second seed changes nothing."""

import base64
from pathlib import Path
from uuid import UUID

import psycopg
from pydantic import SecretStr
from tests.support.migrated_database import MigratedDatabase
from tests.unit.test_simulation_seed_command import Catalogue

from tutor_api.curation.simulation_seed import SimulationSeedMain, main
from tutor_api.settings import ApplicationSettings

KEK = bytes(range(32))


class Rows:
    def counts(self, url: str) -> tuple[int, int, int]:
        with psycopg.connect(url) as connection:
            return tuple(
                int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])  # type: ignore[index]
                for table in ("kb_document", "learner", "learner_history_event")
            )


def _settings(url: str) -> ApplicationSettings:
    return ApplicationSettings(
        _env_file=None,  # type: ignore[call-arg]
        database_url=url,
        tutor_kek=SecretStr(base64.b64encode(KEK).decode()),
        tutor_kek_id=UUID(int=1),
        conflict_confidence_threshold=0.3,
    )


class TestSimulationSeed:
    async def test_the_seed_is_idempotent_and_stress_adds_the_fault(
        self, fresh_database: str
    ) -> None:
        MigratedDatabase().upgrade(fresh_database)
        settings = _settings(fresh_database)
        catalogue = Catalogue()
        documents = (catalogue.document(), catalogue.document("faults"))
        learners = (catalogue.learner(), catalogue.learner(False, 5))
        first = await SimulationSeedMain().run(settings, documents, learners, False)
        assert (first.documents, first.learners, first.events) == (1, 2, 1)
        assert Rows().counts(fresh_database) == (1, 2, 1)
        again = await SimulationSeedMain().run(settings, documents, learners, False)
        assert (again.documents, again.learners, again.events) == (0, 0, 0)
        stressed = await SimulationSeedMain().run(settings, documents, learners, True)
        assert stressed.documents == 1
        assert Rows().counts(fresh_database) == (2, 2, 1)
        held = await SimulationSeedMain().run(settings, documents, learners, True)
        assert held.documents == 0

    def test_the_process_entry_seeds_from_the_files(
        self, fresh_database: str, tmp_path: Path
    ) -> None:
        MigratedDatabase().upgrade(fresh_database)
        catalogue = Catalogue()
        kb = tmp_path / "kb.jsonl"
        roster = tmp_path / "roster.jsonl"
        kb.write_text(catalogue.document().model_dump_json() + "\n", encoding="utf-8")
        roster.write_text(
            catalogue.learner().model_dump_json() + "\n", encoding="utf-8"
        )
        assert main([str(kb), str(roster)], _settings(fresh_database)) == 0
        assert Rows().counts(fresh_database)[0] == 1
