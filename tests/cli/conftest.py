import pytest
from click_async_plugins import ITC
from fastapi.requests import HTTPConnection
from pytest_mock import MockerFixture, MockType
from starlette.datastructures import MutableHeaders


@pytest.fixture
def httpcon(mocker: MockerFixture) -> MockType:
    httpcon = mocker.MagicMock(spec=HTTPConnection)
    httpcon.headers = MutableHeaders({})
    httpcon.client = None
    return httpcon


@pytest.fixture
def itc() -> ITC:
    return ITC()
