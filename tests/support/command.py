"""Run guard-rail tools as subprocesses from tests."""

from __future__ import annotations

import subprocess
from pathlib import Path
from subprocess import CompletedProcess


class GuardrailCommand:
    """Invoke a CLI and return the completed process, never raising."""

    def run(self, args: list[str], cwd: Path) -> CompletedProcess[str]:
        return subprocess.run(
            args,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
        )
