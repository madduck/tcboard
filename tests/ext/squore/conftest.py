import pytest

from tcboard.ext.squore.devinfo import SquoreDeviceInfo
from tcboard.ext.squore.match import SquoreMatch
from tcboard.match import TCMatch


@pytest.fixture
def sqdevinfo() -> SquoreDeviceInfo:
    return SquoreDeviceInfo(
        batteryCharging=True, batteryPercentage=42, deviceid="squore!"
    )


@pytest.fixture
def sqmatch(match: TCMatch) -> SquoreMatch:
    return SquoreMatch.from_match(match)
