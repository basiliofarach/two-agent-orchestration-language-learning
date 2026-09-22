"""Recorded instants come from ClockPort. One adapter may read the wall clock."""

import ast
from pathlib import Path


class WallClockCalls:
    """``datetime.now`` call sites under the two source trees.

    Docstrings mention ``datetime.now()`` and are not calls, so a text search
    would report them. This walk looks at call nodes only. ``SystemClock`` is
    the one allowed call: replay substitutes ``FrozenClock``.
    """

    def __init__(self, roots: tuple[Path, ...], allowed: Path) -> None:
        self._roots = roots
        self._allowed = allowed.resolve()

    def forbidden(self) -> tuple[str, ...]:
        found: list[str] = []
        for root in self._roots:
            for path in sorted(root.rglob("*.py")):
                for line in self._lines(path):
                    if path.resolve() == self._allowed:
                        continue
                    found.append(f"{path}:{line}")
        return tuple(found)

    def _lines(self, path: Path) -> tuple[int, ...]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        lines: list[int] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and self._is_datetime_now(node):
                lines.append(node.lineno)
        return tuple(lines)

    def _is_datetime_now(self, node: ast.Call) -> bool:
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "now":
            return False
        return self._names_datetime(func.value)

    def _names_datetime(self, node: ast.expr) -> bool:
        if isinstance(node, ast.Name):
            return node.id == "datetime"
        if isinstance(node, ast.Attribute):
            return node.attr == "datetime"
        return False


class TestNoWallClockOutsideSystemClock:
    def test_only_system_clock_calls_datetime_now(self) -> None:
        root = Path(__file__).resolve().parents[2]
        sources = (
            root / "tutor-core" / "src",
            root / "tutor-api" / "src",
        )
        allowed = (
            root / "tutor-api" / "src" / "tutor_api" / "adapters" / "system_clock.py"
        )
        assert WallClockCalls(sources, allowed).forbidden() == ()
