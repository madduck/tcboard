from tcboard.devinfo import DeviceInfo


def test_constructor_device_accessor(deviceinfo: DeviceInfo) -> None:
    assert deviceinfo.device == "deviceid"


def test_timestamp_default(deviceinfo: DeviceInfo) -> None:
    assert deviceinfo.timestamp is not None


def test_no_batterystatus(deviceinfo: DeviceInfo) -> None:
    assert deviceinfo.batterystatus is None


def test_str(deviceinfo: DeviceInfo) -> None:
    assert str(deviceinfo) == "deviceid"


def test_debug_repr(deviceinfo: DeviceInfo) -> None:
    assert deviceinfo.debug_repr() == "deviceid"


def test_hash_only_deviceid(deviceinfo: DeviceInfo) -> None:
    other = deviceinfo.model_copy(update={"timestamp": None})
    assert hash(deviceinfo) == hash(other)
    other.deviceid = "other"
    assert hash(deviceinfo) != hash(other)
