import pytest

from tcboard.alert import Alert
from tcboard.devinfo import DeviceInfo


@pytest.fixture
def alert() -> Alert:
    return Alert(
        text="alert text", detail="detail", matchid="matchid", deviceid="deviceid"
    )


@pytest.fixture
def deviceinfo() -> DeviceInfo:
    return DeviceInfo(deviceid="deviceid")
