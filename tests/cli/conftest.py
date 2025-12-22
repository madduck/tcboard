import pytest
from click_async_plugins import ITC


@pytest.fixture
def itc() -> ITC:
    return ITC()
