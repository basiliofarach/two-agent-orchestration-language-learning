"""The synthetic rubric file, when a previous eval left one."""

import json
from json import JSONDecodeError
from pathlib import Path


class RubricScores:
    """Read ``rubric-scores.jsonl`` and render each line canonically.

    A missing file is an empty tuple: the pack then says the scores were
    not supplied. A line that is not a JSON object fails the command.
    Tutor-sourced scores are not read from anywhere else.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    def lines(self) -> tuple[str, ...]:
        """The canonical lines, or none when the file is absent."""
        if not self._path.is_file():
            return ()
        rendered: list[str] = []
        for raw in self._path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            rendered.append(self._canonical(raw))
        return tuple(rendered)

    def _canonical(self, raw: str) -> str:
        try:
            parsed = json.loads(raw)
        except JSONDecodeError as exc:
            msg = "a rubric line is not JSON"
            raise ValueError(msg) from exc
        if not isinstance(parsed, dict):
            msg = "a rubric line must be a JSON object"
            raise ValueError(msg)
        return json.dumps(parsed, sort_keys=True, separators=(",", ":"))
