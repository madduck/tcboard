from tcboard.devinfo import BatteryStatus
from tcboard.ext.squore.devinfo import SquoreDeviceInfo


def test_batterystatus(sqdevinfo: SquoreDeviceInfo) -> None:
    assert sqdevinfo.batterystatus == BatteryStatus(percentage=42, charging=True)


def test_validation_reads_device_into_deviceid(sqdevinfo: SquoreDeviceInfo) -> None:
    di = sqdevinfo.model_dump()
    di["device"] = di.pop("deviceid")
    res = SquoreDeviceInfo.model_validate(di)
    assert di["device"] is res.deviceid
