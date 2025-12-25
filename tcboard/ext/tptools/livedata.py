from datetime import datetime

from pydantic import computed_field
from tptools import Match
from tptools.util import ScoresType

from ...game import Game
from ...livedata import LiveData
from ...livestatus import LiveStatus


class TPData[MatchT: Match](LiveData, extra="forbid"):
    match: MatchT

    @computed_field  # type: ignore[prop-decorator]
    @property
    def matchid(self) -> str:
        return self.match.id

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status(self) -> LiveStatus:
        return LiveStatus.FINISHED

    @property
    def deviceid(self) -> str:
        return "TournamentSoftware"

    @property
    def devinfo(self) -> None:
        return None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def starttime(self) -> datetime | None:
        return self.match.starttime or self.match.time

    @computed_field  # type: ignore[prop-decorator]
    @property
    def endtime(self) -> datetime | None:
        return self.match.endtime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def scores(self) -> ScoresType:
        return self.match.scores

    @computed_field  # type: ignore[prop-decorator]
    @property
    def games(self) -> list[Game]:
        return [Game(score=g, winner=int(g[0] < g[1])) for g in self.scores]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def winner(self) -> int | None:
        if self.match.winner is None:
            return None
        else:
            return int(self.match.winner == "B")  # int(True) → 1, int(False) → 0

    def validate_livedata(self) -> None: ...
