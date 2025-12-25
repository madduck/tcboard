import warnings
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from tcboard.ext.squore.devinfo import SquoreDeviceInfo
from tcboard.ext.squore.livedata import (
    InconsistentStateBug120,
    Metadata,
    SquoreMatchLiveData,
    TimerInfo,
    Timing,
)
from tcboard.game import Game
from tcboard.livestatus import LiveStatus
from tcboard.point import PlayerIndex

from ...conftest import FakeLiveDataFactoryType
from .conftest import LiveDataFactoryType


def test_match_court_nullstring_to_none(LiveDataFactory: LiveDataFactoryType) -> None:
    # https://github.com/obbimi/Squore/issues/96
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        bad_model_dump = LiveDataFactory(court="null").model_dump(
            exclude_computed_fields=True
        )
    assert SquoreMatchLiveData.model_validate(bad_model_dump).court is None


def test_match_warmup(
    LiveDataFactory: LiveDataFactoryType, timerinfo_warmup: TimerInfo
) -> None:
    assert LiveDataFactory(timerInfo=timerinfo_warmup).status == LiveStatus.WARMUP


def test_match_prepare(
    LiveDataFactory: LiveDataFactoryType, timerinfo_prepare: TimerInfo
) -> None:
    assert LiveDataFactory(timerInfo=timerinfo_prepare).status == LiveStatus.PREPARE


def test_match_prep15(
    LiveDataFactory: LiveDataFactoryType, timerinfo_15seconds: TimerInfo
) -> None:
    assert (
        LiveDataFactory(timerInfo=timerinfo_15seconds).status
        == LiveStatus.FIFTEENSECONDS
    )


def test_match_ready(LiveDataFactory: LiveDataFactoryType) -> None:
    assert LiveDataFactory().status == LiveStatus.READY


def test_match_ongoing(
    LiveDataFactory: LiveDataFactoryType, match_ongoing: SquoreMatchLiveData
) -> None:
    assert LiveDataFactory(base=match_ongoing).status == LiveStatus.ONGOING


def test_match_betweengames(
    LiveDataFactory: LiveDataFactoryType,
    match_ongoing: SquoreMatchLiveData,
    timerinfo_beforegame: TimerInfo,
) -> None:
    assert (
        LiveDataFactory(base=match_ongoing, timerInfo=timerinfo_beforegame).status
        == LiveStatus.BETWEENGAMES
    )


def test_match_15seconds(
    LiveDataFactory: LiveDataFactoryType,
    match_ongoing: SquoreMatchLiveData,
    timerinfo_15seconds: TimerInfo,
) -> None:
    assert (
        LiveDataFactory(base=match_ongoing, timerInfo=timerinfo_15seconds).status
        == LiveStatus.FIFTEENSECONDS
    )


def test_match_gameball(
    LiveDataFactory: LiveDataFactoryType, match_ongoing: SquoreMatchLiveData
) -> None:
    assert (
        LiveDataFactory(base=match_ongoing, isGameBall=True).status
        == LiveStatus.GAMEBALL
    )


def test_match_matchball(
    LiveDataFactory: LiveDataFactoryType, match_ongoing: SquoreMatchLiveData
) -> None:
    assert (
        LiveDataFactory(base=match_ongoing, isMatchBall=True).status
        == LiveStatus.MATCHBALL
    )


def test_match_finished(
    LiveDataFactory: LiveDataFactoryType, match_ongoing: SquoreMatchLiveData
) -> None:
    assert (
        LiveDataFactory(base=match_ongoing, isVictoryFor="A").status
        == LiveStatus.FINISHED
    )


def test_match_ongoing_debug_repr_has_result(
    LiveDataFactory: LiveDataFactoryType, match_ongoing: SquoreMatchLiveData
) -> None:
    assert (
        LiveDataFactory(base=match_ongoing, result="1-2").debug_repr()
        == "matchid (1-2)"
    )


@patch("tcboard.ext.squore.livedata.LiveData.debug_repr")
def test_match_debug_repr_super(
    mocked_super_debug_repr: MagicMock,
    LiveDataFactory: LiveDataFactoryType,
    match_base: SquoreMatchLiveData,
) -> None:
    _ = LiveDataFactory(base=match_base, result="1-2").debug_repr()
    mocked_super_debug_repr.assert_called_once_with()


@patch("tcboard.ext.squore.livedata.LiveData.can_come_after")
def test_undo_can_replace(
    mocked_super_can_come_after: MagicMock,
    LiveDataFactory: LiveDataFactoryType,
    FakeLiveDataFactory: FakeLiveDataFactoryType,
) -> None:
    assert LiveDataFactory(isUndo=True).can_come_after(
        FakeLiveDataFactory(status=LiveStatus.ONGOING)
    )
    mocked_super_can_come_after.assert_not_called()


@patch("tcboard.ext.squore.livedata.LiveData.can_come_after")
def test_can_come_after_calls_super(
    mocked_super_can_come_after: MagicMock,
    LiveDataFactory: LiveDataFactoryType,
    FakeLiveDataFactory: FakeLiveDataFactoryType,
) -> None:
    ld = LiveDataFactory()
    other = FakeLiveDataFactory(status=LiveStatus.ONGOING)
    _ = ld.can_come_after(other)

    mocked_super_can_come_after.assert_called_once_with(other)


def test_livescoredevid_is_deviceid(LiveDataFactory: LiveDataFactoryType) -> None:
    devid = "devid"
    assert LiveDataFactory(liveScoreDeviceId=devid).deviceid == devid


def test_devinfo_accessor(
    LiveDataFactory: LiveDataFactoryType, sqmetadata: Metadata
) -> None:
    ld = LiveDataFactory(metadata=sqmetadata.model_copy(update={"device": None}))
    assert ld.devinfo is None
    ld = LiveDataFactory()
    assert isinstance(ld.devinfo, SquoreDeviceInfo)
    assert ld.devinfo.deviceid == ld.deviceid


@pytest.mark.parametrize(
    "inp, out",
    [("A", 0), ("B", 1), (None, None)],
)
def test_winner_accessor(
    inp: str | None,
    out: PlayerIndex | None,
    LiveDataFactory: LiveDataFactoryType,
) -> None:
    assert LiveDataFactory(isVictoryFor=inp).winner == out


def test_starttime_accessor(
    LiveDataFactory: LiveDataFactoryType, now: datetime
) -> None:
    assert LiveDataFactory().starttime == now


def test_endtime_accessor_ongoing(LiveDataFactory: LiveDataFactoryType) -> None:
    assert LiveDataFactory().endtime is None


def test_endtime_accessor_finished(
    LiveDataFactory: LiveDataFactoryType,
    match_finished: SquoreMatchLiveData,
    now: datetime,
) -> None:
    assert LiveDataFactory(base=match_finished).endtime == now


def test_nr_games_finished(match_finished: SquoreMatchLiveData) -> None:
    assert match_finished.nr_games_played() == 5


def test_nr_games_ongoing(match_ongoing: SquoreMatchLiveData) -> None:
    assert match_ongoing.nr_games_played() == 2


def test_scores_base(match_base: SquoreMatchLiveData) -> None:
    assert match_base.scores == []


def test_scores_warmup(match_warmup: SquoreMatchLiveData) -> None:
    assert match_warmup.scores == []


def test_scores_ongoing(match_ongoing: SquoreMatchLiveData) -> None:
    assert match_ongoing.scores == [(11, 9), (11, 7), (4, 6)]


def test_scores_finished(match_finished: SquoreMatchLiveData) -> None:
    assert match_finished.scores == [(11, 9), (11, 7), (10, 12), (3, 11), (11, 13)]


def test_games_base(match_base: SquoreMatchLiveData) -> None:
    assert match_base.games == [Game(score=(0, 0))]


def test_games_warmup(match_warmup: SquoreMatchLiveData) -> None:
    assert match_warmup.games == []


def test_games_ongoing(match_ongoing: SquoreMatchLiveData) -> None:
    assert len(match_ongoing.games) == 3


def test_games_finished(match_finished: SquoreMatchLiveData) -> None:
    assert len(match_finished.games) == 5


def test_validate_base(match_base: SquoreMatchLiveData) -> None:
    match_base.validate_livedata()


def test_validate_warmup(match_warmup: SquoreMatchLiveData) -> None:
    match_warmup.validate_livedata()


def test_validate_ongoing(match_ongoing: SquoreMatchLiveData) -> None:
    match_ongoing.validate_livedata()


def test_validate_finished(match_finished: SquoreMatchLiveData) -> None:
    match_finished.validate_livedata()


def test_validate_squore_bug_120(
    match_finished: SquoreMatchLiveData, now: datetime
) -> None:
    match_finished.timing.append(
        Timing(start=now.isoformat(), end=now.isoformat(), offsets=[])
    )
    with pytest.raises(InconsistentStateBug120):
        match_finished.validate_livedata()
