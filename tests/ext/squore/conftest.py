import pytest

from tcboard.ext.squore.devinfo import SquoreDeviceInfo


@pytest.fixture
def sqdevinfo() -> SquoreDeviceInfo:
    return SquoreDeviceInfo(
        batteryCharging=True, batteryPercentage=42, deviceid="squore!"
    )
