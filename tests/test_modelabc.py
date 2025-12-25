from typing import Any

import pytest

from tcboard.modelabc import ModelABC


class FakeClass(ModelABC):
    data: dict[str, Any] = {}


MODELID = "tests.test_modelabc.FakeClass"


def test_modelid() -> None:
    assert FakeClass().modelid == MODELID


def test_instantiate_from_modelid() -> None:
    data = {"answer": 42}
    model = ModelABC.make_model_instance(data={"data": data}, modelid=MODELID)
    assert isinstance(model, FakeClass)
    assert model.data == data


def test_instantiate_from_class() -> None:
    data = {"answer": 42}
    model = FakeClass.make_model_instance(data={"data": data})
    assert isinstance(model, FakeClass)
    assert model.data == data


def test_instantiate_from_unknown_modelid() -> None:
    with pytest.raises(TypeError, match="Model specialisation not known"):
        _ = ModelABC.make_model_instance(data={}, modelid="nosuchmodel")


def test_instantiate_not_possible_from_base() -> None:
    with pytest.raises(TypeError, match="Model specialisation not known"):
        _ = ModelABC.make_model_instance(data={})
