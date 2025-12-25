from collections.abc import Callable
from datetime import datetime, timedelta
from itertools import zip_longest
from typing import Any, Literal, Protocol, TypedDict

import pytest

from tcboard.ext.squore.devinfo import SquoreDeviceInfo
from tcboard.ext.squore.livedata import (
    Event,
    Format,
    Metadata,
    Players,
    SquoreMatchLiveData,
    TimerInfo,
    Timing,
    When,
)
from tcboard.point import PlayerLetter


class AppDataLiterals(TypedDict):
    appName: Literal["Squore"]
    appPackage: Literal["com.doubleyellow.scoreboard"]


@pytest.fixture
def squoreappdata() -> AppDataLiterals:
    return {"appName": "Squore", "appPackage": "com.doubleyellow.scoreboard"}


@pytest.fixture
def sqplayers() -> Players:
    return Players(A="Jane", B="Mary")


@pytest.fixture
def sqevent() -> Event:
    return Event(name="Tournament!", division="Division!")


class WhenT(TypedDict):
    start: str
    when: When


@pytest.fixture
def sqtime(now: datetime) -> WhenT:
    return {
        "start": now.isoformat(sep="T", timespec="microseconds"),
        "when": When(date=now.date().isoformat(), time=now.time().isoformat()),
    }


@pytest.fixture
def sqformat() -> Format:
    return Format(
        numberOfGamesToWinMatch=3,
        numberOfPointsToWinGame=11,
        useHandInHandOutScoring=False,
    )


@pytest.fixture
def sqcourt() -> int:
    return 42


@pytest.fixture
def sqnocourt() -> None:
    return None


@pytest.fixture
def sqdevinfo() -> SquoreDeviceInfo:
    return SquoreDeviceInfo(batteryCharging=True, batteryPercentage=42)


@pytest.fixture
def sqmetadata(sqdevinfo: SquoreDeviceInfo) -> Metadata:
    return Metadata(sourceID="matchid", device=sqdevinfo)


class GameData(TypedDict):
    result: str
    gamescores: str | None
    score: list[list[str]]
    timing: list[Timing]
    isVictoryFor: PlayerLetter | None


class GameDataFactoryType(Protocol):
    def __call__(
        self,
        game1: tuple[int, int] | None = None,
        game2: tuple[int, int] | None = None,
        game3: tuple[int, int] | None = None,
        game4: tuple[int, int] | None = None,
        game5: tuple[int, int] | None = None,
        /,
    ) -> GameData: ...


@pytest.fixture
def GameDataFactory(now: datetime) -> GameDataFactoryType:
    def factory(
        game1: tuple[int, int] | None = None,
        game2: tuple[int, int] | None = None,
        game3: tuple[int, int] | None = None,
        game4: tuple[int, int] | None = None,
        game5: tuple[int, int] | None = None,
        /,
    ) -> GameData:
        games = []
        result = [0, 0]
        timing: list[Timing] = []
        score: list[list[str]] = []
        endtime = now
        for a, b in [g for g in (game5, game4, game3, game2, game1) if g]:
            games.append("-".join(str(i) for i in (a, b)))
            if a >= 11 or b >= 11:
                result[int(b > a)] += 1
            starttime = endtime - timedelta(seconds=a + b)
            timing.append(
                Timing(
                    start=starttime.isoformat(),
                    end=endtime.isoformat(),
                    offsets=[o + 1 for o in range(a + b)],
                )
            )
            endtime = starttime - timedelta(seconds=90)
            scores = []
            for _a, _b in zip_longest(range(a), range(b), fillvalue=None):
                if _a is not None:
                    scores.append(f"L{_a + 1}--")
                if _b is not None:
                    scores.append(f"R--{_b + 1}")

            score.append(scores)

        isVictoryFor: PlayerLetter | None
        match result:
            case (3, _):
                isVictoryFor = "A"
            case (_, 3):
                isVictoryFor = "A"
            case _:
                isVictoryFor = None

        return GameData(
            result="-".join(str(i) for i in result),
            gamescores=",".join(games[::-1]) if games else None,
            score=score[::-1],
            timing=timing[::-1],
            isVictoryFor=isVictoryFor,
        )

    return factory


@pytest.fixture
def match_base(
    GameDataFactory: GameDataFactoryType,
    squoreappdata: AppDataLiterals,
    sqcourt: int,
    sqplayers: Players,
    sqtime: WhenT,
    sqformat: Format,
    sqevent: Event,
    sqmetadata: Metadata,
) -> SquoreMatchLiveData:
    return SquoreMatchLiveData(
        court=sqcourt,
        players=sqplayers,
        server="A",
        serveSide="R",
        isGameBall=False,
        isHandOut=True,
        isMatchBall=False,
        liveScoreDeviceId="abcdef",
        lockState="Unlocked",
        **sqtime,
        event=sqevent,
        format=sqformat,
        metadata=sqmetadata,
        **squoreappdata,
        **GameDataFactory(),
    )


type LiveDataFactoryType = Callable[..., SquoreMatchLiveData]


@pytest.fixture
def LiveDataFactory(match_base: SquoreMatchLiveData) -> LiveDataFactoryType:
    def updater(
        base: SquoreMatchLiveData = match_base, **updates: Any
    ) -> SquoreMatchLiveData:
        return base.model_copy(update=updates)

    return updater


@pytest.fixture(params=[120, 240])
def timerinfo_warmup(request: pytest.FixtureRequest) -> TimerInfo:
    return TimerInfo(type="Warmup", totalSeconds=request.param)


@pytest.fixture
def timerinfo_prepare() -> TimerInfo:
    return TimerInfo(type="UntilStartOfFirstGame", totalSeconds=60)


@pytest.fixture
def timerinfo_beforegame() -> TimerInfo:
    return TimerInfo(type="UntilStartOfNextGame", totalSeconds=120)


@pytest.fixture
def timerinfo_15seconds() -> TimerInfo:
    return TimerInfo(type="UntilStartOfNextGame", totalSeconds=15)


@pytest.fixture
def match_warmup(
    timerinfo_warmup: TimerInfo, LiveDataFactory: LiveDataFactoryType
) -> SquoreMatchLiveData:
    return LiveDataFactory(timerInfo=timerinfo_warmup)


@pytest.fixture
def match_ongoing(
    GameDataFactory: GameDataFactoryType, LiveDataFactory: LiveDataFactoryType
) -> SquoreMatchLiveData:
    gamedata = GameDataFactory((11, 9), (11, 7), (4, 6))
    return LiveDataFactory(**gamedata)


@pytest.fixture
def match_finished(
    GameDataFactory: GameDataFactoryType, LiveDataFactory: LiveDataFactoryType
) -> SquoreMatchLiveData:
    gamedata = GameDataFactory((11, 9), (11, 7), (10, 12), (3, 11), (11, 13))
    return LiveDataFactory(**gamedata)
