"""``build`` through the CLI, then realise, freeze and verify on what it wrote.

The composition root, the cache-only fetch, the file store and the manifest
are real. The artefacts are small fixtures in each source's real format; the
role model is the echo fixture.
"""

import io
import json
import shutil
from pathlib import Path

import pytest
from tests.support.repository import RepositoryPaths
from tests.unit.sim.test_build import Sources

from tutor_api.adapters.persistence.knowledge_base import PassageSplitter
from tutor_sim.cli import SimulationCli
from tutor_sim.composition import SimulationCompositionRoot
from tutor_sim.domain.models.source import SourceRecord
from tutor_sim.settings import SimulationSettings


class BuildWorkspace:
    """A catalogue, a seeded cache and a dataset root in one temporary directory."""

    def settings(
        self, tmp_path: Path, records: tuple[SourceRecord, ...], cache: Path
    ) -> SimulationSettings:
        catalogue = tmp_path / "sources.json"
        catalogue.write_text(
            json.dumps([record.model_dump(mode="json") for record in records]),
            encoding="utf-8",
        )
        return SimulationSettings(
            dataset_dir=tmp_path / "dataset",
            cache_dir=cache,
            sources_path=catalogue,
            offline=True,
            role_fixture=True,
            evidence_dir=tmp_path / "evidence",
            runtime_pin_path=tmp_path / "runtime.toml",
        )

    def fixture(self, tmp_path: Path) -> SimulationSettings:
        records, bodies = Sources().all(tmp_path / "dataset" / "public" / "authored")
        cache = tmp_path / "cache"
        cache.mkdir()
        by_id = {record.source_id: record for record in records}
        for source_id, body in bodies.items():
            (cache / by_id[source_id].sha256).write_bytes(body)
        return self.settings(tmp_path, records, cache)

    def run(self, settings: SimulationSettings, command: str) -> tuple[int, str]:
        errors = io.StringIO()
        code = SimulationCli(SimulationCompositionRoot(settings), errors).main(
            [command]
        )
        return code, errors.getvalue()


def test_build_then_realise_freeze_and_verify(tmp_path: Path) -> None:
    workspace = BuildWorkspace()
    settings = workspace.fixture(tmp_path)

    code, output = workspace.run(settings, "build")
    assert code == 0, output
    assert "KB documents (restricted)" in output
    root = settings.dataset_dir
    assert (root / "restricted" / "kb" / "documents.jsonl").is_file()
    assert not (root / "public" / "kb" / "documents.jsonl").exists()
    assert (root / "public" / "learners" / "roster.jsonl").is_file()
    assert (root / "plan.json").is_file()

    summaries = {
        "realise": "cases into restricted/stimuli (0 discarded after 3 attempts)",
        "freeze": "cases: restricted/manifest.json",
        "verify": "manifest verified: every file in restricted/ matches its digest",
    }
    for command, summary in summaries.items():
        code, output = workspace.run(settings, command)
        assert code == 0, f"{command}: {output}"
        assert summary in output, output
    manifest = json.loads(
        (root / "restricted" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["files"]
    assert {item["tree"] for item in manifest["files"]} == {"restricted"}
    assert len(manifest["sources"]) == len(
        json.loads(settings.sources_path.read_text(encoding="utf-8"))
    )


def test_the_seed_splits_each_built_sentence_into_its_own_passage(
    tmp_path: Path,
) -> None:
    workspace = BuildWorkspace()
    settings = workspace.fixture(tmp_path)
    assert workspace.run(settings, "build")[0] == 0
    path = settings.dataset_dir / "restricted" / "kb" / "documents.jsonl"
    documents = [json.loads(line) for line in path.read_text().splitlines()]
    wiki_b1 = next(d for d in documents if d["topic_id"] == "cefr-sp-wiki-auto-B1")
    a2 = next(d for d in documents if d["topic_id"] == "cefr-sp-wiki-auto-A2")
    assert PassageSplitter().split(wiki_b1["content"]) == ("They argued about it .",)
    assert PassageSplitter().split(a2["content"]) == ("The river is long .",)
    score_a1 = next(d for d in documents if d["topic_id"] == "cefr-sp-score-A1")
    sentences = score_a1["content"].count("\n\n") + 1
    assert len(PassageSplitter().split(score_a1["content"])) == sentences


def test_a_corrupted_cache_stops_the_build_before_any_plan(tmp_path: Path) -> None:
    workspace = BuildWorkspace()
    settings = workspace.fixture(tmp_path)
    for artefact in settings.cache_dir.iterdir():
        artefact.write_bytes(b"tampered")

    code, output = workspace.run(settings, "build")

    assert code == 1
    assert "digest mismatch" in output
    assert not (settings.dataset_dir / "plan.json").exists()


_REPOSITORY = RepositoryPaths().root()
_CACHE = _REPOSITORY / ".cache" / "sim"


@pytest.mark.skipif(
    not _CACHE.is_dir() or not any(_CACHE.iterdir()),
    reason="the pinned artefacts are not cached on this machine",
)
def test_the_committed_catalogue_builds_from_the_local_cache(tmp_path: Path) -> None:
    public = _REPOSITORY / "datasets" / "sim" / "unreleased" / "public"
    workspace = BuildWorkspace()
    settings = workspace.settings(tmp_path, (), _CACHE).model_copy(
        update={"sources_path": public / "sources.json"}
    )
    shutil.copytree(public / "authored", settings.dataset_dir / "public" / "authored")

    code, output = workspace.run(settings, "build")

    assert code == 0, output
    assert "KB documents (restricted)" in output
