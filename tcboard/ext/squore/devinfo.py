from pydantic import ConfigDict

from ...devinfo import BatteryStatus, DeviceInfo


class SquoreDeviceInfo(DeviceInfo):
    model_config = ConfigDict(extra="ignore")  # TODO: deviceid vs device alias

    batteryCharging: bool
    batteryPercentage: int

    @property
    def batterystatus(self) -> BatteryStatus:
        return BatteryStatus(
            percentage=self.batteryPercentage, charging=self.batteryCharging
        )
