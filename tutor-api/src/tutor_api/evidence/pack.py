"""Regenerate the compliance pack from records already in the log."""

import hashlib
import json
import subprocess
from pathlib import Path

from tutor_api.evidence.articles import Article10, Article12, Article14, Article15
from tutor_api.evidence.body import EvidenceSources, PackBody
from tutor_core.domain.ports.clock import ClockPort

__all__ = ["EvidencePack", "EvidenceSources", "RepositoryPins"]


class EvidencePack:
    """One directory of compliance evidence (REQ-POLICY, REQ-AUDIT).

    The pack is built from values it was given. It does not write to the
    audit tables. Learner-facing text is redacted again on the way out,
    and history snapshots are not copied (REQ-MINOR). Generating twice
    with the same clock is byte-identical. A different clock changes only
    ``generated_at``.
    """

    def __init__(self, clock: ClockPort) -> None:
        self._clock = clock

    def files(self, sources: EvidenceSources, body: PackBody) -> dict[str, str]:
        """Return path to text. ``manifest.json`` holds the only timestamp."""
        if sources.field_label != body.rubric_label:
            msg = "the field label must be synthetic-only"
            raise ValueError(msg)
        generated = self._clock.now().isoformat()
        return {
            "manifest.json": self._manifest(sources, body, generated),
            "article-10.md": Article10(sources, body).text(),
            "article-12.md": Article12(sources, body).text(),
            "article-14.md": Article14(body).text(),
            "article-15.md": Article15(body).text(),
            "exhibits.json": self._exhibits(body),
        }

    def write(self, directory: Path, sources: EvidenceSources, body: PackBody) -> None:
        """Write the pack. Named files are replaced. Other files are left."""
        directory.mkdir(parents=True, exist_ok=True)
        for name, text in self.files(sources, body).items():
            (directory / name).write_text(text, encoding="utf-8")

    def _manifest(
        self, sources: EvidenceSources, body: PackBody, generated: str
    ) -> str:
        payload = {
            **sources.model_dump(mode="json"),
            "generated_at": generated,
            "rubric_lines": len(body.rubric_lines),
            "field_comparison": body.field_comparison,
        }
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"

    def _exhibits(self, body: PackBody) -> str:
        return json.dumps(body.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"


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
