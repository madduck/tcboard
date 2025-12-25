# needed < 3.14 so that annotations aren't evaluated
from __future__ import annotations

import traceback
import uuid
from datetime import datetime
from types import TracebackType
from typing import Any, Self, cast

from pydantic import (
    UUID4,
    BaseModel,
    Field,
)


class Alert(BaseModel):
    text: str
    id: UUID4 = Field(default_factory=uuid.uuid4)
    detail: str | None = None
    matchid: str | None = None
    deviceid: str | None = None
    timestamp: datetime | None = None
    traceback: str | None = Field(default=None, repr=False)
    cleared: datetime | None = None

    def model_post_init(self, _: Any) -> None:
        if self.timestamp is None:
            self.timestamp = datetime.now()

    @classmethod
    def from_exception(cls, exc: Exception, **kwargs: Any) -> Self:
        text = kwargs.pop("text", None) or str(exc)
        return cls(text=text, traceback=cls.format_tb(exc.__traceback__), **kwargs)

    @staticmethod
    def format_tb(tback: TracebackType | None) -> str | None:
        if tback is None:
            return None
        return "\n".join(traceback.format_tb(tback))

    def clear(self, timestamp: datetime | None = None) -> None:
        self.cleared = timestamp if timestamp is not None else datetime.now()

    def __hash__(self) -> int:
        return hash((self.text, self.matchid, self.cleared))

    def __eq__(self, other: object) -> bool:
        try:
            other = cast(Alert, other)
            return (self.text, self.matchid, self.cleared) == (
                other.text,
                other.matchid,
                other.cleared,
            )
        except AttributeError:
            return False

    def __str__(self) -> str:
        text = self.text
        if self.detail:
            text = f"{text}: {self.detail}"

        ret = [text]
        if self.matchid is not None:
            ret.append(f"matchid={self.matchid}")

        if self.deviceid is not None:
            ret.append(f"deviceid={self.deviceid}")

        return ", ".join(ret)
