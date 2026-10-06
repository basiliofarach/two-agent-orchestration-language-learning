"""Recorded instants are ``AwareDatetime`` on a ``Timestamped`` record (DEC-0010)."""

import importlib
import pkgutil
from datetime import datetime
from types import ModuleType

import pytest
from pydantic import BaseModel

import tutor_api
import tutor_core
from tutor_core.domain.models.timestamps import (
    AwareDatetime,
    InstantFields,
    Timestamped,
)


class FirstPartyModels:
    """Every ``BaseModel`` subclass defined in ``tutor_core`` and ``tutor_api``."""

    def __init__(self, *packages: ModuleType) -> None:
        self._packages = packages

    def all(self) -> tuple[type[BaseModel], ...]:
        for package in self._packages:
            for module in pkgutil.walk_packages(
                package.__path__, prefix=f"{package.__name__}."
            ):
                importlib.import_module(module.name)
        roots = tuple(package.__name__ for package in self._packages)
        return tuple(
            model
            for model in self._subclasses(BaseModel)
            if model.__module__.startswith(roots)
        )

    def _subclasses(self, base: type[BaseModel]) -> tuple[type[BaseModel], ...]:
        found: list[type[BaseModel]] = []
        for child in base.__subclasses__():
            found.append(child)
            found.extend(self._subclasses(child))
        return tuple(found)


class ModelName:
    """Pytest id for a model class."""

    def __call__(self, model: type[BaseModel]) -> str:
        return model.__name__


_MODELS = FirstPartyModels(tutor_core, tutor_api).all()


class TestInstantFields:
    def test_an_aware_field_is_aware(self) -> None:
        class Probe(BaseModel):
            at: AwareDatetime

        assert InstantFields(Probe).aware() == ("at",)
        assert InstantFields(Probe).naive() == ()

    def test_a_plain_datetime_is_naive(self) -> None:
        class Probe(BaseModel):
            at: datetime

        assert InstantFields(Probe).naive() == ("at",)

    def test_an_optional_or_nested_datetime_is_found(self) -> None:
        class Probe(BaseModel):
            stopped: AwareDatetime | None = None
            history: tuple[datetime, ...] = ()

        assert InstantFields(Probe).aware() == ("stopped",)
        assert InstantFields(Probe).naive() == ("history",)

    def test_a_field_without_a_datetime_is_neither(self) -> None:
        class Probe(BaseModel):
            name: str

        assert InstantFields(Probe).aware() == ()
        assert InstantFields(Probe).naive() == ()


class TestTimestampedBase:
    def test_a_plain_datetime_on_a_timestamped_record_is_refused(self) -> None:
        with pytest.raises(TypeError, match="recorded_at"):

            class Record(Timestamped):
                recorded_at: datetime

    def test_a_timestamped_record_without_an_instant_is_refused(self) -> None:
        with pytest.raises(TypeError, match="no AwareDatetime"):

            class Record(Timestamped):
                name: str

    def test_an_aware_record_is_frozen_and_forbids_extra(self) -> None:
        class Record(Timestamped):
            recorded_at: AwareDatetime

        assert Record.model_config.get("frozen") is True
        assert Record.model_config.get("extra") == "forbid"


class TestEveryFirstPartyModel:
    def test_the_walk_reaches_the_audit_records(self) -> None:
        names = {model.__name__ for model in _MODELS}
        assert {"TurnAuditRecord", "GateEvaluation", "HistoryItem"} <= names

    @pytest.mark.parametrize("model", _MODELS, ids=ModelName())
    def test_no_model_stores_a_naive_datetime(self, model: type[BaseModel]) -> None:
        assert InstantFields(model).naive() == ()

    @pytest.mark.parametrize("model", _MODELS, ids=ModelName())
    def test_a_model_with_an_instant_inherits_timestamped(
        self, model: type[BaseModel]
    ) -> None:
        if InstantFields(model).aware():
            assert issubclass(model, Timestamped)
