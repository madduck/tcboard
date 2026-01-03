from datetime import datetime

import pytest
from pytest_mock import MockerFixture

from tcboard.exceptions import CourtMismatchError, MatchStateConflict, RogueDeviceError
from tcboard.game import Game
from tcboard.livestatus import LiveStatus
from tcboard.match import TCMatch
from tcboard.matchslot import MatchSlot
from tcboard.matchstate import MatchState

from .conftest import (
    FakeLiveData,
    FakeLiveDataFactoryType,
    MatchStateFactoryType,
)


def test_timestamp_default(matchstate: MatchState[FakeLiveData]) -> None:
    assert matchstate.timestamp is not None


def test_timestamp_from_livedata(
    match: TCMatch, FakeLiveDataFactory: FakeLiveDataFactoryType, now: datetime
) -> None:
    assert (
        MatchState(match=match, livedata=FakeLiveDataFactory(timestamp=now)).timestamp
        is now
    )


def test_ack(matchstate: MatchState[FakeLiveData]) -> None:
    assert not matchstate.acked
    matchstate.ack()
    assert matchstate.acked
    matchstate.unack()  # type: ignore[unreachable]
    assert not matchstate.acked


def test_lock(matchstate: MatchState[FakeLiveData]) -> None:
    assert not matchstate.locked
    matchstate.lock()
    assert matchstate.locked
    matchstate.unlock()  # type: ignore[unreachable]
    assert not matchstate.locked


def test_reset(
    livedata: FakeLiveData, MatchStateFactory: MatchStateFactoryType
) -> None:
    matchstate = MatchStateFactory(livedata=livedata)
    assert matchstate.livedata
    matchstate.reset()
    assert not matchstate.livedata


@pytest.mark.parametrize("status", [None] + list(LiveStatus))
def test_slot(
    MatchStateFactory: MatchStateFactoryType,
    FakeLiveDataFactory: FakeLiveDataFactoryType,
    status: LiveStatus | None,
) -> None:
    if status is None:
        livedata = None
    else:
        livedata = FakeLiveDataFactory(status=status)

    assert MatchStateFactory(livedata=livedata).slot == {
        LiveStatus.FINISHED: MatchSlot.FINISHED,
        LiveStatus.EXTERNAL: MatchSlot.HIDDEN,
        LiveStatus.UNKNOWN: MatchSlot.UNKNOWN,
        None: MatchSlot.PENDING,
    }.get(status, MatchSlot.CURRENT)


@pytest.mark.xfail
def test_receive_calls_livedata_validate(
    matchstate: MatchState[FakeLiveData],
    livedata: FakeLiveData,
    mocker: MockerFixture,
) -> None:
    validate = mocker.patch.object(livedata, "validate_livedata", autospec=False)
    matchstate.validate_and_receive_livedata(livedata)
    validate.assert_called_once_with(livedata)


def test_receive_initial_livedata(
    matchstate: MatchState[FakeLiveData],
    livedata: FakeLiveData,
) -> None:
    matchstate.validate_and_receive_livedata(livedata)
    assert matchstate.livedata is livedata
    assert matchstate.timestamp is livedata.timestamp


def test_receive_court_mismatch(
    MatchStateFactory: MatchStateFactoryType,
    FakeLiveDataFactory: FakeLiveDataFactoryType,
) -> None:
    matchstate = MatchStateFactory(court=1)
    with pytest.raises(CourtMismatchError):
        matchstate.validate_and_receive_livedata(FakeLiveDataFactory(court=2))


def test_receive_device_mismatch(
    MatchStateFactory: MatchStateFactoryType,
    FakeLiveDataFactory: FakeLiveDataFactoryType,
) -> None:
    matchstate = MatchStateFactory(deviceid="one")
    with pytest.raises(RogueDeviceError):
        matchstate.validate_and_receive_livedata(FakeLiveDataFactory(deviceid="two"))


def test_receive_out_of_sequence(
    MatchStateFactory: MatchStateFactoryType,
    FakeLiveDataFactory: FakeLiveDataFactoryType,
) -> None:
    matchstate = MatchStateFactory(status=LiveStatus.GAMEBALL)
    with pytest.raises(MatchStateConflict):
        matchstate.validate_and_receive_livedata(
            FakeLiveDataFactory(status=LiveStatus.WARMUP)
        )


def test_receive_in_sequence(
    MatchStateFactory: MatchStateFactoryType,
    FakeLiveDataFactory: FakeLiveDataFactoryType,
) -> None:
    matchstate = MatchStateFactory(status=LiveStatus.GAMEBALL)
    matchstate.validate_and_receive_livedata(
        FakeLiveDataFactory(status=LiveStatus.ONGOING)
    )


def test_status_property_no_livedata(matchstate: MatchState[FakeLiveData]) -> None:
    assert matchstate.status is None


def test_status_property_from_livedata(
    matchstate: MatchState[FakeLiveData], livedata: FakeLiveData
) -> None:
    matchstate.validate_and_receive_livedata(livedata)
    assert matchstate.status == str(LiveStatus.UNKNOWN).lower()


def test_debug_repr(matchstate: MatchState[FakeLiveData]) -> None:
    assert matchstate.debug_repr() == str(matchstate)


def test_str(matchstate: MatchState[FakeLiveData]) -> None:
    assert str(matchstate).endswith(matchstate.match.id)


def test_str_locked(matchstate: MatchState[FakeLiveData]) -> None:
    matchstate.lock()
    assert "🔒" in str(matchstate)


def test_str_acked(matchstate: MatchState[FakeLiveData]) -> None:
    matchstate.ack()
    assert "✓" in str(matchstate)


def test_str_no_time(matchstate: MatchState[FakeLiveData]) -> None:
    matchstate = matchstate.model_copy(
        update={"match": matchstate.match.model_copy(update={"time": None})}
    )
    assert "??:??" in str(matchstate)


def test_str_with_scores(
    FakeLiveDataFactory: FakeLiveDataFactoryType,
    MatchStateFactory: MatchStateFactoryType,
) -> None:
    ld = FakeLiveDataFactory(
        games=[
            Game(score=sc, winner=int(sc[1] > sc[0]))
            for sc in ((11, 4), (12, 10), (11, 9))
        ]
    )
    ms = MatchStateFactory(livedata=ld)
    assert "3-0" in str(ms)


def test_time_pending(
    match: TCMatch,
    now: datetime,
) -> None:
    ms = MatchState[FakeLiveData](
        match=match.model_copy(update={"time": now}), livedata=None
    )
    assert ms.time == now


def test_time_current(
    FakeLiveDataFactory: FakeLiveDataFactoryType,
    MatchStateFactory: MatchStateFactoryType,
    now: datetime,
) -> None:
    ld = FakeLiveDataFactory(starttime=now, status=LiveStatus.ONGOING)
    ms = MatchStateFactory(livedata=ld)
    assert ms.time == now


def test_time_finished(
    FakeLiveDataFactory: FakeLiveDataFactoryType,
    MatchStateFactory: MatchStateFactoryType,
    now: datetime,
) -> None:
    ld = FakeLiveDataFactory(endtime=now, status=LiveStatus.FINISHED)
    ms = MatchStateFactory(livedata=ld)
    assert ms.time == now
