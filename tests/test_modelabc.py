from typing import Any, Self

import pytest

from tcboard.modelabc import ABCWithRegistry


class FakeClass(ABCWithRegistry):
    def __init__(self, data: Any) -> None:
        self.data = data

    @classmethod
    def model_validate(cls, obj: Any) -> Self:
        return cls(data=obj)


MODELID = "tests.test_modelabc.FakeClass"


def test_modelid() -> None:
    assert FakeClass(data=None).modelid == MODELID


def test_instantiate_from_modelid() -> None:
    model = ABCWithRegistry.make_model_instance(MODELID, data={})
    assert isinstance(model, FakeClass)
    assert model.data == {}


def test_instantiate_from_unknown_modelid() -> None:
    with pytest.raises(TypeError, match="Model specialisation not known"):
        _ = ABCWithRegistry.make_model_instance("nosuchmodel", data={})
