"""What an operator sees while a long command runs.

A one-line bar on a terminal, nothing while the stream is redirected, and
always one summary line at the end. The stream is injected, so a test reads
exactly what an operator would.
"""

from typing import TextIO

_LINE = 100


class CommandProgress:
    """Count items done out of a known total, then say what happened."""

    def __init__(self, stream: TextIO, width: int = 30) -> None:
        self._stream = stream
        self._width = width
        self._live = stream.isatty()
        self._total = 0
        self._done = 0

    def start(self, total: int) -> None:
        """Begin a bar of ``total`` items."""
        self._total = total
        self._done = 0
        self._draw("")

    def step(self, detail: str) -> None:
        """One item finished; ``detail`` names it."""
        self._done += 1
        self._draw(detail)

    def finish(self, summary: str) -> None:
        """End the bar's line and print the summary, terminal or not."""
        if self._live and self._total:
            self._stream.write("\n")
        self._stream.write(f"{summary}\n")
        self._stream.flush()

    def _draw(self, detail: str) -> None:
        if not self._live or not self._total:
            return
        filled = self._width * self._done // self._total
        bar = "#" * filled + "-" * (self._width - filled)
        percent = 100 * self._done // self._total
        line = f"\r  [{bar}] {percent:3d}% {self._done}/{self._total} {detail}"
        self._stream.write(line.ljust(_LINE)[:_LINE])
        self._stream.flush()
