"""Shared checks for frozen Pydantic models (DEC-0002, DEC-0010)."""

import pytest
from pydantic import BaseModel, ValidationError


class ListCoercion:
    """Replace tuples with lists so a model must coerce them back."""

    def as_lists(self, value: object) -> object:
        if isinstance(value, tuple | list):
            return [self.as_lists(item) for item in value]
        if isinstance(value, dict):
            return {key: self.as_lists(item) for key, item in value.items()}
        return value


class ModelId:
    """Pytest id for a model instance."""

    def __call__(self, model: BaseModel) -> str:
        return type(model).__name__


class FrozenModelChecks:
    """Assignment, extra fields, equality, and tuple coercion."""

    def __init__(self) -> None:
        self._lists = ListCoercion()

    def assert_assignment_raises(self, model: BaseModel) -> None:
        field_name = next(iter(type(model).model_fields))
        with pytest.raises(ValidationError):
            setattr(model, field_name, getattr(model, field_name))

    def assert_extra_forbidden(self, model: BaseModel) -> None:
        payload = model.model_dump()
        payload["undeclared"] = "no"
        with pytest.raises(ValidationError):
            type(model).model_validate(payload)

    def assert_equal_and_hashable(self, model: BaseModel) -> None:
        clone = type(model).model_validate(model.model_dump())
        assert clone == model
        assert hash(clone) == hash(model)
        assert len({clone, model}) == 1

    def assert_list_coerced_to_tuple(self, model: BaseModel) -> None:
        payload = self._lists.as_lists(model.model_dump())
        restored = type(model).model_validate(payload)
        assert restored == model
        for name in type(model).model_fields:
            if isinstance(getattr(model, name), tuple):
                assert isinstance(getattr(restored, name), tuple)
