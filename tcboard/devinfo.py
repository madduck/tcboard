# needed < 3.14 so that annotations aren't evaluated
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import (
    BaseModel,
)

from .modelabc import ModelABC


class BatteryStatus(BaseModel):
    percentage: int
    charging: bool


class DeviceInfo(ModelABC):
    deviceid: str | None = None
    timestamp: datetime | None = None

    def model_post_init(self, ctx: Any) -> None:
        if self.timestamp is None:
            self.timestamp = (ctx or {}).get("timestamp") or datetime.now()

    @property
    def device(self) -> str | None:
        return self.deviceid

    @property
    def batterystatus(self) -> BatteryStatus | None:
        return None

    def debug_repr(self) -> str:
        return str(self)

    def __str__(self) -> str:
        return self.device or "(no device ID)"

    def __hash__(self) -> int:
        return hash(self.device)
