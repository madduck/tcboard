import itertools
from datetime import datetime
from typing import Literal, Never

from pydantic import BaseModel, Field, computed_field, field_validator
from tptools.util import ScoresType

from ...alert import Alert
from ...exceptions import TCBoardException
from ...game import Game
from ...livedata import LiveData
from ...livestatus import LiveStatus
from .devinfo import SquoreDeviceInfo
from .point import PlayerLetter, Point, ServerSide, make_point_from_squore_line

type ServerType = PlayerLetter
type LockStateType = (
    Literal["Unlocked"]
    | Literal["UnlockedManual"]
    | Literal["LockedEndOfMatch"]
    | Literal["LockedIdleTime"]
    | None
)  # TODO: timeout lock


class InconsistentStateBug120(TCBoardException): ...


class Players(BaseModel, extra="forbid"):
    A: str
    B: str


class PlayersProps(BaseModel, extra="forbid"):
    A: str | None = None
    B: str | None = None


class Colors(PlayersProps): ...


class Countries(PlayersProps): ...


class Clubs(PlayersProps): ...


class When(BaseModel, extra="forbid"):
    date: str
    time: str


class Event(BaseModel, extra="forbid"):
    name: str
    division: str


class Format(BaseModel, extra="forbid"):
    numberOfPointsToWinGame: int
    numberOfGamesToWinMatch: int
    useHandInHandOutScoring: bool = False


class Timing(BaseModel, extra="forbid"):
    start: str
    end: str
    offsets: list[int] | None = None


class Wifi(BaseModel, extra="forbid"):
    ipaddress: str | None = None


class Metadata(BaseModel, extra="forbid"):
    sourceID: str
    device: SquoreDeviceInfo | None = None
    source: str | None = None
    version: int | None = None
    language: str | None = None
    wifi: Wifi | None = None
    shareURL: str | None = None
    sourceFeedbackState: (
        Literal["SourceAcceptedFinalResult"] | Literal["SourceRejectedResult"] | None
    ) = None
    sourcePostResultUrl: str | None = None


class TimerInfo(BaseModel, extra="forbid"):
    type: (
        Literal["Warmup"]
        | Literal["UntilStartOfFirstGame"]
        | Literal["UntilStartOfNextGame"]
    )
    totalSeconds: int


class SquoreMatchLiveData(LiveData, extra="forbid"):
    appName: Literal["Squore"]
    appPackage: Literal["com.doubleyellow.scoreboard"]
    clubs: Clubs | None = None
    colors: Colors | None = None
    countries: Countries | None = None
    event: Event
    format: Format
    gamescores: str | None = None
    isGameBall: bool
    isHandOut: bool
    isMatchBall: bool
    isVictoryFor: PlayerLetter | None = None
    isUndo: bool = False
    lastScorer: PlayerLetter | None = None
    liveScoreDeviceId: str
    lockState: LockStateType = None
    maxNrOfPowerPlays: int | None = None
    metadata: Metadata
    players: Players
    result: str
    score: list[list[str]] = Field(default_factory=list[list[str]])
    server: ServerType
    serveSide: ServerSide
    start: str
    timerInfo: TimerInfo | None = None
    timing: list[Timing] = Field(default_factory=list[Timing])
    when: When

    @property
    def matchid(self) -> str:
        return self.metadata.sourceID

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status(self) -> LiveStatus:
        if self.timerInfo:
            if self.timerInfo.type == "Warmup":
                return LiveStatus.WARMUP

            if self.timerInfo.type == "UntilStartOfFirstGame":
                return LiveStatus.PREPARE

            elif self.timerInfo.totalSeconds == 15:
                return LiveStatus.FIFTEENSECONDS

            return LiveStatus.BETWEENGAMES

        elif self.score:
            if self.isMatchBall:
                return LiveStatus.MATCHBALL

            elif self.isGameBall:
                return LiveStatus.GAMEBALL

            elif self.isVictoryFor:
                return LiveStatus.FINISHED

            return LiveStatus.ONGOING

        return LiveStatus.READY

    def can_come_after(self, other: LiveData) -> bool:
        if self.isUndo:
            return True

        return super().can_come_after(other)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def deviceid(self) -> str:
        return self.liveScoreDeviceId

    @computed_field  # type: ignore[prop-decorator]
    @property
    def devinfo(self) -> SquoreDeviceInfo | None:
        if self.metadata.device is None:
            return None

        return self.metadata.device.model_copy(update={"deviceid": self.deviceid})

    @computed_field  # type: ignore[prop-decorator]
    @property
    def starttime(self) -> datetime:
        return datetime.fromisoformat(self.start)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def endtime(self) -> datetime | None:
        if self.status == LiveStatus.FINISHED:
            return datetime.fromisoformat(self.timing[-1].end)
        return None

    def nr_games_played(self) -> int:
        return sum(int(x) for x in self.result.split("-"))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def scores(self) -> ScoresType:
        if self.gamescores is None:
            return []

        ret = []
        for gscore in self.gamescores.split(","):
            ret.append((int((s := gscore.split("-"))[0]), int(s[1])))
        return ret

    def _get_scoreline(
        self, scores: list[str], offsets: list[int] | None
    ) -> list[Point]:
        ret: list[Point] = []

        prev_offset = 0
        for point, offset in itertools.zip_longest(scores, offsets or []):
            ret.append(
                make_point_from_squore_line(point, duration=offset - prev_offset)
            )
            prev_offset = offset

        return ret

    @computed_field  # type: ignore[prop-decorator]
    @property
    def games(self) -> list[Game]:
        nr_games_played = self.nr_games_played()
        ret = []

        is_cur = False
        for i, ((a, b), points, timings) in enumerate(
            zip(
                self.scores,
                self.score,
                [t for t in self.timing if t.offsets is not None],
                strict=True,
            )
        ):
            scoreline = self._get_scoreline(points, timings.offsets)

            is_cur = i == nr_games_played
            ret.append(
                Game(
                    score=(a, b),
                    starttime=datetime.fromisoformat(timings.start),
                    endtime=None if is_cur else datetime.fromisoformat(timings.end),
                    winner=None if is_cur else int(a < b),
                    scoreline=scoreline,
                )
            )

        if (
            not is_cur
            and self.status >= LiveStatus.READY
            and self.status < LiveStatus.FINISHED
        ) or (
            len(self.timing) == 1
            and self.timing[0].offsets is None
            and self.score == []
        ):
            ret.append(Game(score=(0, 0)))
        return ret

    @computed_field  # type: ignore[prop-decorator]
    @property
    def winner(self) -> int | None:
        if self.isVictoryFor is None:
            return None
        return {"A": 0, "B": 1}[self.isVictoryFor]

    def validate_livedata(self) -> Never | None:
        if len([t for t in self.timing if t.offsets is not None]) != len(self.scores):
            raise InconsistentStateBug120(
                Alert(
                    text="Inconsistent Squore state (bug #120)",
                    matchid=self.matchid,
                    deviceid=self.deviceid,
                ),
            )
        return None

    def debug_repr(self) -> str:
        if self.status >= LiveStatus.ONGOING:
            return f"{self.matchid} ({self.result})"

        else:
            return super().debug_repr()

    @field_validator("court", mode="before")
    @classmethod
    def handle_no_court_as_string(
        cls, data: Literal["null"] | int | None
    ) -> int | None:
        return None if data == "null" else data
