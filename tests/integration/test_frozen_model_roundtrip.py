"""Frozen models survive JSON and come back equal."""

from pydantic import BaseModel
from tests.support.samples import Samples


class TestFrozenModelJsonRoundTrip:
    def test_each_frozen_model_round_trips_through_json(self) -> None:
        for model in Samples().frozen_instances():
            assert isinstance(model, BaseModel)
            restored = type(model).model_validate_json(model.model_dump_json())
            assert restored == model
