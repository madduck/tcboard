import itertools
from datetime import datetime
from typing import Any, Never

from pydantic import computed_field, field_validator
from squoredata import (
    SquoreMatchLiveData as SquoreMatchLiveDataBase,
)
from squoredata import (
    TimerInfo,
    Timing,
    When,
    make_point_from_squore_line,
)
from tptools.util import ScoresType

from ...alert import Alert
from ...exceptions import TCBoardException
from ...game import Game
from ...livedata import LiveData
from ...livestatus import LiveStatus
from ...point import Point
from .devinfo import SquoreDeviceInfo

__all__ = [
    "InconsistentStateBug120",
    "SquoreMatchLiveData",
    "TimerInfo",
    "Timing",
    "When",
]


class InconsistentStateBug120(TCBoardException): ...


class SquoreMatchLiveData(LiveData, SquoreMatchLiveDataBase):
    """Live Squore data, wired into the tcboard ``LiveData`` abstraction.

    ``squoredata`` provides the data structure and the derived ``status``,
    ``scores`` and ``games``.  tcboard needs those to speak its own ``Game``,
    ``Point`` and ``LiveStatus`` types, so they are overridden here, together
    with the ``LiveData`` accessors the squoredata model leaves out.
    """

    court: int | None  # type: ignore[assignment]

    # Intentional override here. Squore sends strings for courts,
    # but we use integers internally.

    @field_validator("court", mode="before")
    @classmethod
    def _coerce_to_int_or_none(cls, v: Any) -> int | None:
        if v == "null":
            # https://github.com/obbimi/Squore/issues/96
            return None
        elif not isinstance(v, int):
            return int(v)
        return v

    @property
    def matchid(self) -> str:
        return self.metadata.sourceID

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status(self) -> LiveStatus:  # type: ignore[override]
        # Intentionally tcboard's LiveStatus; squoredata has its own, identical
        # enum that tcboard code cannot use for comparisons.
        sqstatus = SquoreMatchLiveDataBase.status.fget(self)  # type: ignore[attr-defined]

        try:
            return LiveStatus[sqstatus.name]

        except KeyError:  # pragma: nocover
            return LiveStatus.UNKNOWN

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

        return SquoreDeviceInfo.model_validate(
            self.metadata.device.model_dump() | {"deviceid": self.deviceid}
        )

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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def scores(self) -> ScoresType:
        # LiveData declares this abstract; squoredata implements it.  Delegate
        # explicitly so the ABC is satisfied with the tcboard ScoresType.
        return SquoreMatchLiveDataBase.scores.fget(self)  # type: ignore[attr-defined,no-any-return]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def winner(self) -> int | None:
        # LiveData declares this abstract; squoredata implements it.
        return SquoreMatchLiveDataBase.winner.fget(self)  # type: ignore[attr-defined,no-any-return]

    def _get_scoreline(  # type: ignore[override]
        self, scores: list[str], offsets: list[int] | None
    ) -> list[Point]:
        ret: list[Point] = []

        prev_offset = 0
        for point, offset in itertools.zip_longest(scores, offsets or []):
            squorepoint = make_point_from_squore_line(
                point, duration=offset - prev_offset
            )
            ret.append(
                Point(
                    server=squorepoint.server,
                    serveside=squorepoint.serveside,
                    player=squorepoint.player,
                    data=squorepoint.data,
                    duration=squorepoint.duration,
                )
            )
            prev_offset = offset

        return ret

    @computed_field  # type: ignore[prop-decorator]
    @property
    def games(self) -> list[Game]:  # type: ignore[override]
        # Intentionally returns tcboard Game objects, built from tcboard Points.
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
