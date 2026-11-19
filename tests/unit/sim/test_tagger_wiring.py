"""TreeTagger is wired into ``build`` from a directory and the ``[pos_tagger]`` pin.

The files are checked against their digests when the harness is wired.
Nothing here runs the binary.
"""

import hashlib
from pathlib import Path

import pytest
from tests.unit.sim.test_kernel import OfflineSettings

from tutor_sim.adapters.pos_tagger import TaggingFailed
from tutor_sim.composition import SimulationCompositionRoot, TaggerChoice
from tutor_sim.settings import SimulationSettings


class TaggerFiles:
    """A TreeTagger directory laid out like the download, with fake bytes."""

    def write(self, directory: Path, pin: Path, binary: bytes = b"bin") -> None:
        (directory / "bin").mkdir(parents=True)
        (directory / "bin" / "tree-tagger").write_bytes(binary)
        (directory / "english.par").write_bytes(b"par")
        pin.write_text(
            "[pos_tagger]\n"
            'version = "3.2.3"\n'
            f'binary_sha256 = "{hashlib.sha256(b"bin").hexdigest()}"\n'
            f'parameter_file_sha256 = "{hashlib.sha256(b"par").hexdigest()}"\n',
            encoding="utf-8",
        )


def _settings(tmp_path: Path) -> SimulationSettings:
    return (
        OfflineSettings()
        .build(tmp_path, True)
        .model_copy(update={"treetagger_dir": tmp_path / "treetagger"})
    )


class TestTaggerChoice:
    def test_no_directory_means_no_tagger(self, tmp_path: Path) -> None:
        assert TaggerChoice().choose(OfflineSettings().build(tmp_path, True)) is None

    def test_pinned_files_give_the_pinned_version(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        TaggerFiles().write(tmp_path / "treetagger", settings.runtime_pin_path)
        tagger = TaggerChoice().choose(settings)
        assert tagger is not None
        assert tagger.revision() == "3.2.3"

    def test_a_binary_that_is_not_the_pinned_one_is_refused(
        self, tmp_path: Path
    ) -> None:
        settings = _settings(tmp_path)
        TaggerFiles().write(
            tmp_path / "treetagger", settings.runtime_pin_path, binary=b"other"
        )
        with pytest.raises(TaggingFailed, match="not the pinned file"):
            TaggerChoice().choose(settings)

    def test_the_harness_wires_with_a_tagger(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        TaggerFiles().write(tmp_path / "treetagger", settings.runtime_pin_path)
        SimulationCompositionRoot(settings).wire().close()


class TestRepositoryPin:
    def test_the_committed_pin_names_treetagger_3_2_3(self) -> None:
        from tutor_sim.adapters.role_model import PosTaggerPin

        pin = PosTaggerPin(Path("config/runtime.toml"))
        assert pin.version() == "3.2.3"
        assert len(pin.binary_sha256()) == 64
