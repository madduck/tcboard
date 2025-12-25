from datetime import datetime
from unittest.mock import MagicMock

import pytest
from tptools import Match

from tcboard.ext.tptools.livedata import TPData
from tcboard.game import Game
from tcboard.livestatus import LiveStatus
from tcboard.point import PlayerIndex, PlayerLetter


@pytest.fixture
def tpmatch() -> Match:
    return MagicMock(spec=Match)


@pytest.fixture
def tpdata(tpmatch: Match) -> TPData[Match]:
    return TPData[Match](court=42, match=tpmatch)


def test_matchid(tpdata: TPData[Match]) -> None:
    matchid = "matchid"
    tpdata.match.id = matchid
    assert tpdata.matchid == matchid


def test_status(tpdata: TPData[Match]) -> None:
    assert tpdata.status == LiveStatus.FINISHED


def test_deviceid(tpdata: TPData[Match]) -> None:
    assert tpdata.deviceid == "TournamentSoftware"


def test_devinfo(tpdata: TPData[Match]) -> None:
    assert tpdata.devinfo is None


def test_starttime(tpdata: TPData[Match], now: datetime) -> None:
    tpdata.match.starttime = None
    tpdata.match.time = None

    assert tpdata.starttime is None

    tpdata.match.starttime = now
    assert tpdata.starttime == now

    tpdata.match.starttime = None
    assert tpdata.starttime is None

    tpdata.match.time = now
    assert tpdata.starttime == now


def test_endtime(tpdata: TPData[Match], now: datetime) -> None:
    tpdata.match.endtime = None
    assert tpdata.endtime is None

    tpdata.match.endtime = now
    assert tpdata.endtime == now


def test_scores(tpdata: TPData[Match]) -> None:
    scores = [(11, 9), (9, 11)]
    tpdata.match.scores = scores
    assert tpdata.scores == scores


def test_games(tpdata: TPData[Match]) -> None:
    tpdata.match.scores = [(11, 9), (11, 9), (9, 11), (11, 9)]
    assert len(tpdata.games) == 4
    assert tpdata.games[0] == Game(score=(11, 9), winner=0)
    assert tpdata.games[1] == Game(score=(11, 9), winner=0)
    assert tpdata.games[2] == Game(score=(9, 11), winner=1)
    assert tpdata.games[3] == Game(score=(11, 9), winner=0)


@pytest.mark.parametrize(
    "tpwin, exp",
    [
        (None, None),
        ("A", 0),
        ("B", 1),
    ],
)
def test_winner(
    tpdata: TPData[Match], tpwin: PlayerLetter | None, exp: PlayerIndex | None
) -> None:
    tpdata.match.winner = tpwin
    assert tpdata.winner == exp
