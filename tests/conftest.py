from collections.abc import Callable
from datetime import datetime
from typing import Any, cast

import pytest
from pydantic import computed_field
from tptools.util import ScoresType

from tcboard.alert import Alert
from tcboard.devinfo import DeviceInfo
from tcboard.game import Game
from tcboard.livedata import LiveData
from tcboard.livestatus import LiveStatus


@pytest.fixture
def alert() -> Alert:
    return Alert(
        text="alert text", detail="detail", matchid="matchid", deviceid="deviceid"
    )


@pytest.fixture
def deviceinfo() -> DeviceInfo:
    return DeviceInfo(deviceid="deviceid")


class FakeLiveData(LiveData):
    fakedata: dict[str, Any] = {}

    @property
    def matchid(self) -> str:
        return cast(str, self.fakedata.get("matchid", "(no matchid)"))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status(self) -> LiveStatus:
        return cast(LiveStatus, self.fakedata.get("status", LiveStatus.UNKNOWN))

    @property
    def deviceid(self) -> str:
        return cast(str, self.fakedata.get("deviceid"))

    @property
    def devinfo(self) -> DeviceInfo | None:
        return cast(DeviceInfo | None, self.fakedata.get("devinfo"))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def starttime(self) -> datetime | None:
        return cast(datetime | None, self.fakedata.get("starttime"))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def endtime(self) -> datetime | None:
        return cast(datetime | None, self.fakedata.get("endtime"))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def scores(self) -> ScoresType:
        return cast(ScoresType, self.fakedata.get("scores", []))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def games(self) -> list[Game]:
        return cast(list[Game], self.fakedata.get("games", []))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def winner(self) -> int | None:
        return cast(int | None, self.fakedata.get("winner"))

    def validate_livedata(self) -> None:
        return None


type FakeLiveDataFactoryType = Callable[..., FakeLiveData]


@pytest.fixture
def FakeLiveDataFactory() -> FakeLiveDataFactoryType:
    def factory(
        court: int | None = None, timestamp: datetime | None = None, **data: Any
    ) -> FakeLiveData:
        return FakeLiveData(court=court, timestamp=timestamp, fakedata=data)

    return factory
