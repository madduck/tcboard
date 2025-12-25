from tcboard.devinfo import BatteryStatus
from tcboard.ext.squore.devinfo import SquoreDeviceInfo


def test_batterystatus(sqdevinfo: SquoreDeviceInfo) -> None:
    assert sqdevinfo.batterystatus == BatteryStatus(percentage=42, charging=True)
