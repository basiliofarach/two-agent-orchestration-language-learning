"""Write the evidence pack. ``python -m tutor_api.evidence`` from ``tutor-api/``."""

import sys
from pathlib import Path

from tutor_api.adapters.system_clock import SystemClock
from tutor_api.evidence.pack import EvidencePack, EvidenceSources, RepositoryPins
from tutor_api.settings import ApplicationSettings


class PackPaths:
    """Find the workspace root by ``uv.lock``."""

    def root(self) -> Path:
        """The directory that contains ``uv.lock``."""
        for parent in Path(__file__).resolve().parents:
            if (parent / "uv.lock").is_file():
                return parent
        msg = "uv.lock was not found"
        raise FileNotFoundError(msg)


class EvidenceCommand:
    """One command. It does not open the audit tables.

    The chain status is ``not_checked`` for that reason. A session's chain
    is verified when the audit route is read. The field section is labelled
    synthetic-only until FIELD-01 records tutor-sourced inputs.
    """

    def __init__(self, root: Path, destination: Path) -> None:
        self._root = root
        self._destination = destination

    def run(self) -> None:
        """Write the pack under ``destination``."""
        settings = ApplicationSettings()
        pins = RepositoryPins(self._root)
        text = settings.model_pin_path.read_text(encoding="utf-8")
        sources = EvidenceSources(
            commit=pins.commit(),
            lockfile_sha256=pins.lockfile_sha256(),
            model_revision=self._revision(text),
            runtime=sys.version.split()[0],
            policy_version="prototype-1",
            chain_status="not_checked",
            field_label="synthetic-only",
        )
        EvidencePack(SystemClock()).write(self._destination, sources)

    def _revision(self, text: str) -> str:
        for line in text.splitlines():
            if line.strip().startswith("weights_sha"):
                return line.split("=", 1)[1].strip().strip('"')
        return "unpinned"


class EvidenceModule:
    """The module entry. Wired here, outside the request container."""

    @staticmethod
    def main() -> None:
        """Write ``evidence/`` at the workspace root."""
        root = PackPaths().root()
        EvidenceCommand(root, root / "evidence").run()


if __name__ == "__main__":
    EvidenceModule.main()
