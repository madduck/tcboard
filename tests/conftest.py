from collections.abc import AsyncGenerator, Callable
from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest
import pytest_asyncio
from pydantic import computed_field
from tptools import (
    Court,
    Draw,
    DrawType,
    Entry,
    Event,
    MatchStatus,
    Player,
    ScoresType,
    Stage,
)

from tcboard import TCBoard, TCMatch, TCTournament
from tcboard.alert import Alert
from tcboard.dbmanager import DBManager
from tcboard.devinfo import DeviceInfo
from tcboard.game import Game
from tcboard.livedata import LiveData
from tcboard.livestatus import LiveStatus
from tcboard.matchstate import MatchState


@pytest.fixture
def now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
def alert() -> Alert:
    return Alert(
        text="alert text", detail="detail", matchid="matchid", deviceid="deviceid"
    )


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


@pytest.fixture
def livedata(FakeLiveDataFactory: FakeLiveDataFactoryType) -> LiveData:
    return FakeLiveDataFactory()


@pytest.fixture
def player1() -> Player:
    return Player(id=1, firstname="Player 1")


@pytest.fixture
def player2() -> Player:
    return Player(id=2, firstname="Player 2")


@pytest.fixture
def entry1(event: Event, player1: Player) -> Entry:
    return Entry(id=1, event=event, player1=player1)


@pytest.fixture
def entry2(event: Event, player2: Player) -> Entry:
    return Entry(id=2, event=event, player1=player2)


@pytest.fixture
def event() -> Event:
    return Event(id=1, name="Event")


@pytest.fixture
def stage(event: Event) -> Stage:
    return Stage(id=1, name="Stage", event=event)


@pytest.fixture
def draw(stage: Stage) -> Draw:
    return Draw(id=1, name="Draw", type=DrawType.MONRAD, size=8, stage=stage)


@pytest.fixture
def court1() -> Court:
    return Court(id=1, name="Court 1")


@pytest.fixture
def court2() -> Court:
    return Court(id=2, name="Court 2")


type MatchFactoryType = Callable[..., TCMatch]


@pytest.fixture
def MatchFactory(
    draw: Draw, now: datetime, court1: Court, entry1: Entry, entry2: Entry
) -> MatchFactoryType:
    defaults: dict[str, Any] = {
        "id": "42-1",
        "matchnr": 1,
        "draw": draw,
        "time": now,
        "court": court1,
        "status": MatchStatus.PENDING,
        "starttime": None,
        "endtime": None,
        "A": entry1,
        "B": entry2,
    }

    def factory(**kwargs: Any) -> TCMatch:
        return TCMatch(**defaults | kwargs)

    return factory


@pytest.fixture
def match(MatchFactory: MatchFactoryType) -> TCMatch:
    return MatchFactory()


@pytest.fixture
def deviceinfo() -> DeviceInfo:
    return DeviceInfo(deviceid="deviceid")


@pytest_asyncio.fixture
async def dbmanager() -> AsyncGenerator[DBManager]:
    async with DBManager(file=None) as db:
        yield db


@pytest_asyncio.fixture
async def dbmanager_inited(dbmanager: DBManager) -> AsyncGenerator[DBManager]:
    await dbmanager.init_tables()
    yield dbmanager


type MatchStateFactoryType = Callable[..., MatchState]


@pytest.fixture
def MatchStateFactory(
    FakeLiveDataFactory: FakeLiveDataFactoryType, match: TCMatch
) -> MatchStateFactoryType:
    def factory(
        livedata: FakeLiveData | None = None, **livedataargs: Any
    ) -> MatchState:
        if livedata is None and livedataargs:
            livedata = FakeLiveDataFactory(**livedataargs)
        return MatchState(match=match, livedata=livedata)

    return factory


@pytest.fixture
def matchstate(MatchStateFactory: MatchStateFactoryType) -> MatchState:
    return MatchStateFactory()


@pytest.fixture
def tournament(
    MatchFactory: MatchFactoryType,
    draw: Draw,
    now: datetime,
    court1: Court,
    court2: Court,
    entry1: Entry,
    entry2: Entry,
) -> TCTournament:
    tourn = TCTournament(name="test tournament")
    tourn.add_court(court1)
    tourn.add_court(court2)
    tourn.add_draw(draw)
    tourn.add_entries((entry1, entry2))

    for m in range(4):
        mid = m * 2
        tourn.add_match(
            MatchFactory(
                id=str(mid), matchnr=mid, court=court1, time=now + timedelta(hours=m)
            )
        )
        tourn.add_match(
            MatchFactory(
                id=str(mid + 1),
                matchnr=mid + 1,
                court=court2,
                time=now + timedelta(hours=m),
            )
        )

    return tourn


@pytest.fixture
def tcboard(tournament: TCTournament) -> TCBoard:
    return TCBoard(tournament=tournament)
