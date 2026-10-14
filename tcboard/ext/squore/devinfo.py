from squoredata import SquoreDeviceInfo as SquoreDeviceInfoBase

from ...devinfo import BatteryStatus, DeviceInfo


class SquoreDeviceInfo(SquoreDeviceInfoBase, DeviceInfo):
    """Squore device information integrated with tcboard's device abstraction.

    Multiple inheritance is needed because the squoredata base carries the
    Squore fields and battery data, while tcboard's :class:`DeviceInfo` adds the
    ``_modelid`` serialisation used for the board's polymorphic round-trip.
    """

    @property
    def batterystatus(self) -> BatteryStatus:  # type: ignore[override]
        # Intentionally returns tcboard's BatteryStatus, not squoredata's
        # structurally identical one; the two projects keep separate types.
        return BatteryStatus(
            percentage=self.batteryPercentage, charging=self.batteryCharging
        )
