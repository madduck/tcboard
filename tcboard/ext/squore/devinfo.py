from typing import Any

from pydantic import model_validator

from ...devinfo import BatteryStatus, DeviceInfo

_NONEXISTENT = object()


class SquoreDeviceInfo(DeviceInfo):
    batteryCharging: bool
    batteryPercentage: int

    @model_validator(mode="before")
    @classmethod
    def _rename_device(cls, data: Any) -> Any:
        if (
            isinstance(data, dict)
            and (dev := data.get("device", _NONEXISTENT)) is not _NONEXISTENT
        ):
            data = {k: v for k, v in data.items() if k != "device"} | {"deviceid": dev}
        return data

    @property
    def batterystatus(self) -> BatteryStatus:
        return BatteryStatus(
            percentage=self.batteryPercentage, charging=self.batteryCharging
        )
