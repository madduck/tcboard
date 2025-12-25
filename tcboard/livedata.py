# needed < 3.14 so that annotations aren't evaluated
from __future__ import annotations

from abc import abstractmethod
from datetime import datetime
from typing import Any, Never

from pydantic import (
    BaseModel,
    computed_field,
    field_serializer,
)
from tptools.util import ScoresType

from .devinfo import DeviceInfo
from .game import Game, Result
from .livestatus import LiveStatus
from .modelabc import ABCWithRegistry


class LiveData(BaseModel, ABCWithRegistry):
    court: int | None
    timestamp: datetime | None = None

    def model_post_init(self, ctx: Any) -> None:
        if self.timestamp is None:
            self.timestamp = (ctx or {}).get("timestamp") or datetime.now()

    @computed_field  # type: ignore[prop-decorator]
    @property
    @abstractmethod
    def matchid(self) -> str: ...

    @computed_field  # type: ignore[prop-decorator]
    @property
    @abstractmethod
    def status(self) -> LiveStatus: ...

    @field_serializer("status", mode="plain")
    def _status_as_string(self, _: Any) -> str:
        return str(self.status)

    def can_come_after(self, other: LiveData) -> bool:
        return self.status.can_come_after(other.status)

    @property
    @abstractmethod
    def deviceid(self) -> str: ...

    @property
    @abstractmethod
    def devinfo(self) -> DeviceInfo | None: ...

    @computed_field  # type: ignore[prop-decorator]
    @property
    @abstractmethod
    def starttime(self) -> datetime | None: ...

    @computed_field  # type: ignore[prop-decorator]
    @property
    @abstractmethod
    def endtime(self) -> datetime | None: ...

    @computed_field  # type: ignore[prop-decorator]
    @property
    @abstractmethod
    def scores(self) -> ScoresType: ...

    @computed_field  # type: ignore[prop-decorator]
    @property
    @abstractmethod
    def games(self) -> list[Game]: ...

    @computed_field  # type: ignore[prop-decorator]
    @property
    def matchscore(self) -> Result:
        ret = [0, 0]
        for game in self.games:
            if game.winner is None:
                break
            ret[game.winner] += 1
        return ret

    @computed_field  # type: ignore[prop-decorator]
    @property
    @abstractmethod
    def winner(self) -> int | None: ...

    @abstractmethod
    def validate_livedata(self) -> Never | None: ...

    def debug_repr(self) -> str:
        return f"{self.matchid} ({self.status.short})"

    def __str__(self) -> str:
        return f"{self.matchid} ({self.status})"
