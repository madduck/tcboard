# needed < 3.14 so that annotations aren't evaluated
from __future__ import annotations

from abc import abstractmethod
from collections.abc import MutableMapping
from datetime import datetime
from typing import Any, Never

from pydantic import (
    SerializerFunctionWrapHandler,
    computed_field,
    field_serializer,
    model_serializer,
    model_validator,
)
from tptools.util import ScoresType

from .devinfo import DeviceInfo
from .game import Game, Result
from .livestatus import LiveStatus
from .modelabc import ModelABC


class LiveData(ModelABC):
    court: int | None
    timestamp: datetime | None = None

    def model_post_init(self, ctx: Any) -> None:
        if self.timestamp is None:
            self.timestamp = (ctx or {}).get("timestamp") or datetime.now()

    @property
    @abstractmethod
    def matchid(self) -> str: ...

    @model_serializer(mode="wrap")
    def _add_matchid(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        # must call super()'s model_serializer, unfortunately.
        # See https://github.com/pydantic/pydantic/discussions/12664
        ret: dict[str, Any] = super()._add_modelid(handler)
        ret["_matchid"] = self.matchid
        return ret

    @model_validator(mode="before")
    @classmethod
    def _remove_matchid_from_data(cls, data: Any) -> Any:
        if isinstance(data, MutableMapping):
            data.pop("_matchid", None)

        return data

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
