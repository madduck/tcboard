# needed < 3.14 so that annotations aren't evaluated
from __future__ import annotations

import hashlib
import traceback
from datetime import datetime
from types import TracebackType
from typing import Any, Protocol, Self, cast

from pydantic import (
    BaseModel,
    Field,
    computed_field,
)


class AlertClearCallback(Protocol):
    def __call__(self, alert: Alert, timestamp: datetime) -> None: ...


class Alert(BaseModel):
    text: str
    detail: str | None = None
    matchid: str | None = None
    deviceid: str | None = None
    timestamp: datetime | None = None
    traceback: str | None = Field(default=None, repr=False)
    cleared: datetime | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def id(self) -> str:
        """The alert ID, derived from its content (not timestamp or cleared)."""
        hash = hashlib.sha256()
        for value in (
            self.text,
            self.detail,
            self.matchid,
            self.deviceid,
            self.traceback,
        ):
            hash.update(b"\x00" if value is None else value.encode())
            hash.update(b"\x1f")
        return hash.hexdigest()

    def model_post_init(self, _: Any) -> None:
        if self.timestamp is None:
            self.timestamp = datetime.now()
        self._clear_callback: AlertClearCallback | None = None

    @classmethod
    def from_exception(cls, exc: Exception, **kwargs: Any) -> Self:
        text = kwargs.pop("text", None) or str(exc)
        return cls(text=text, traceback=cls.format_tb(exc.__traceback__), **kwargs)

    @staticmethod
    def format_tb(tback: TracebackType | None) -> str | None:
        if tback is None:
            return None
        return "\n".join(traceback.format_tb(tback))

    def set_clear_callback(self, callback: AlertClearCallback) -> None:
        self._clear_callback = callback

    def clear(self, timestamp: datetime | None = None) -> None:
        self.cleared = timestamp if timestamp is not None else datetime.now()
        if callable(self._clear_callback):
            self._clear_callback(self, self.cleared)

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
