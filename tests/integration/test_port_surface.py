"""The ports package is abstract, and the audit sink cannot mutate."""

import importlib
import inspect
import re
from abc import ABC
from pathlib import Path
from types import ModuleType

import tutor_core.domain.ports as ports_package
from tutor_core.domain.ports.audit_sink import AuditSinkPort


class PortModules:
    """Import each port module under ``domain/ports`` except the package init."""

    def __init__(self) -> None:
        self._root = Path(ports_package.__file__).resolve().parent

    def load(self) -> tuple[ModuleType, ...]:
        loaded: list[ModuleType] = []
        for path in sorted(self._root.glob("*.py")):
            if path.name == "__init__.py":
                continue
            loaded.append(
                importlib.import_module(f"tutor_core.domain.ports.{path.stem}")
            )
        return tuple(loaded)


class PublicClasses:
    """Classes defined in a module, ignoring imported names."""

    def in_module(self, module: ModuleType) -> tuple[type, ...]:
        found: list[type] = []
        for name, value in inspect.getmembers(module, inspect.isclass):
            if name.startswith("_"):
                continue
            if value.__module__ != module.__name__:
                continue
            found.append(value)
        return tuple(found)


class TestPortSurface:
    def test_port_modules_are_abstract(self) -> None:
        modules = PortModules().load()
        assert len(modules) == 15
        classes = [
            cls for module in modules for cls in PublicClasses().in_module(module)
        ]
        assert len(classes) == 16
        for cls in classes:
            assert issubclass(cls, ABC)
            assert cls.__abstractmethods__

    def test_audit_sink_exposes_no_mutating_method(self) -> None:
        forbidden = re.compile(r"update|delete|remove|edit|patch", re.IGNORECASE)
        names = [name for name, _ in inspect.getmembers(AuditSinkPort)]
        matches = [name for name in names if forbidden.search(name)]
        assert matches == []
