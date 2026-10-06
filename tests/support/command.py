"""Run guard-rail tools as subprocesses from tests."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from subprocess import CompletedProcess


class GuardrailCommand:
    """Invoke a CLI and return the completed process, never raising.

    Pytest puts the src roots on ``pythonpath`` because macOS hides the
    editable ``.pth`` files (gh-113659). A subprocess does not get that
    setting, so the same roots go on ``PYTHONPATH`` here.
    """

    def run(self, args: list[str], cwd: Path) -> CompletedProcess[str]:
        env = os.environ.copy()
        roots = os.pathsep.join(
            str(cwd / member / "src") for member in ("tutor-core", "tutor-api")
        )
        prior = env.get("PYTHONPATH")
        env["PYTHONPATH"] = roots if not prior else roots + os.pathsep + prior
        return subprocess.run(
            args,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
