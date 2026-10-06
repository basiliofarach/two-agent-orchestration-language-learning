"""Regenerate the compliance pack from records already in the log."""

import hashlib
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tutor_core.domain.ports.clock import ClockPort


class EvidenceSources(BaseModel):
    """What the manifest pins. Supplied by the command, not read ad hoc."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    commit: str = Field(min_length=1)
    lockfile_sha256: str = Field(min_length=64, max_length=64)
    model_revision: str = Field(min_length=1)
    runtime: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    chain_status: Literal["intact", "broken", "not_checked"]
    field_label: str = Field(min_length=1)


class EvidencePack:
    """One directory of compliance evidence (REQ-POLICY, REQ-AUDIT).

    The pack is built from values it was given. It does not write to the
    audit tables. Learner text is not copied in: the sections cite the
    controls, and the prompts that were logged were already redacted
    (REQ-MINOR). Generating twice with the same clock is byte-identical.
    A different clock changes only ``generated_at``.
    """

    def __init__(self, clock: ClockPort) -> None:
        self._clock = clock

    def files(self, sources: EvidenceSources) -> dict[str, str]:
        """Return path to text. ``manifest.json`` holds the only timestamp."""
        generated = self._clock.now().isoformat()
        chain = sources.chain_status
        return {
            "manifest.json": self._manifest(sources, generated),
            "article-10.md": (
                "# Article 10\n\n"
                "Cites REQ-KB, REQ-HISTORY and REQ-MINOR. "
                "The curated corpus, the history allowlist, and redaction "
                "at the input boundary are the controls. "
                f"Policy version {sources.policy_version}.\n"
            ),
            "article-12.md": (
                "# Article 12\n\n"
                "Cites REQ-AUDIT and REQ-POLICY. "
                f"Chain verification: {chain}.\n"
            ),
            "article-14.md": (
                "# Article 14\n\n"
                "Cites REQ-GATES and REQ-DASH. "
                "The four gates run in order, and approve, edit, override "
                "and stop each append a human action.\n"
            ),
            "article-15.md": (
                "# Article 15\n\n"
                "Cites REQ-ACCURACY, REQ-EVAL and REQ-FIELD. "
                f"Drift report label: {sources.field_label}. "
                "Tutor-sourced inputs are not in this pack, so the "
                "synthetic baseline is synthetic-only.\n"
            ),
        }

    def write(self, directory: Path, sources: EvidenceSources) -> None:
        """Write the pack. Existing files in ``directory`` are replaced."""
        directory.mkdir(parents=True, exist_ok=True)
        for name, text in self.files(sources).items():
            (directory / name).write_text(text, encoding="utf-8")

    def _manifest(self, sources: EvidenceSources, generated: str) -> str:
        return (
            "{\n"
            f'  "commit": "{sources.commit}",\n'
            f'  "lockfile_sha256": "{sources.lockfile_sha256}",\n'
            f'  "model_revision": "{sources.model_revision}",\n'
            f'  "runtime": "{sources.runtime}",\n'
            f'  "policy_version": "{sources.policy_version}",\n'
            f'  "chain_status": "{sources.chain_status}",\n'
            f'  "field_label": "{sources.field_label}",\n'
            f'  "generated_at": "{generated}"\n'
            "}\n"
        )


class RepositoryPins:
    """Commit and lockfile hash for the manifest. Read-only."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def commit(self) -> str:
        """``git rev-parse HEAD``. A missing git directory is an error."""
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self._root,
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()

    def lockfile_sha256(self) -> str:
        """SHA-256 of ``uv.lock``."""
        digest = hashlib.sha256((self._root / "uv.lock").read_bytes()).hexdigest()
        return digest
