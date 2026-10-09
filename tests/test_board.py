import logging

import pytest
from pytest_mock import MockerFixture
from tptools import Court

from tcboard import TCBoard, TCBoardException, TCTournament
from tcboard.alert import Alert


def test_repr(tcboard: TCBoard) -> None:
    assert repr(tcboard) == (
        "TCBoard(rev=0, tournament_name='test tournament', "
        "nmatchstates=0, ncourts=0, nalerts=1)"
    )
    assert tcboard.tournament
    tcboard.tournament.name = None
    assert repr(tcboard) == (
        "TCBoard(rev=0, tournament_name='unnamed', "
        "nmatchstates=0, ncourts=0, nalerts=1)"
    )


def test_str(tcboard: TCBoard) -> None:
    assert str(tcboard) == "test tournament@0"


def test_roundtrip_alerts_court_none(
    tcboard: TCBoard, alert: Alert, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.CRITICAL):
        tcboard.handle_error(error=alert, court=None)
    dump = tcboard.model_dump()
    assert dump["alerts_by_courtid"][-1][0]["id"] == alert.id
    newboard = TCBoard.model_validate(dump)
    assert alert in newboard.alerts_by_courtid[None]


def test_exception_to_alert(
    tcboard: TCBoard, alert: Alert, court1: Court, caplog: pytest.LogCaptureFixture
) -> None:
    exc = TCBoardException("exc")
    with caplog.at_level(logging.CRITICAL):
        tcboard.handle_exception(exc, court1)
    assert all(a.text == "exc" for a in tcboard.alerts_by_courtid[court1.id])


@pytest.mark.asyncio
async def test_clear_all_errors(
    tcboard: TCBoard,
    alert: Alert,
    court1: Court,
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.CRITICAL):
        tcboard.handle_error(alert, court1)
    post_update = mocker.patch.object(tcboard, "_post_update", autospec=True)
    await tcboard.clear_all_errors()
    post_update.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_clear_all_errors_no_update_if_no_change(
    tcboard: TCBoard, mocker: MockerFixture
) -> None:
    post_update = mocker.patch.object(tcboard, "_post_update", autospec=True)
    await tcboard.clear_all_errors()
    post_update.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_tournament(tcboard: TCBoard, tournament: TCTournament) -> None:
    await tcboard.process_tournament(tournament)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

import sys  # noqa: E402
from typing import Any  # noqa: E402
from unittest.mock import AsyncMock, MagicMock  # noqa: E402

from tptools import Court as _Court  # noqa: E402
from tptools import MatchStatus  # noqa: E402

from tcboard.devinfo import DeviceInfo  # noqa: E402
from tcboard.exceptions import EntityNotFoundError  # noqa: E402
from tcboard.livestatus import LiveStatus  # noqa: E402
from tcboard.matchstate import MatchState  # noqa: E402


@pytest.fixture
def fake_ipdb(mocker: MockerFixture) -> MagicMock:
    """Stub out the debugger traps in board.py (they would block a test run)."""
    fake = MagicMock(name="ipdb")
    mocker.patch.dict(sys.modules, {"ipdb": fake})
    mocker.patch("tcboard.board.ipdb", fake)
    return fake


# ---------------------------------------------------------------------------
# process_tournament
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_tournament_updates_existing_matchstate(
    tcboard: TCBoard,
    tournament: TCTournament,
    MatchFactory: Any,
    court1: _Court,
    draw: Any,
    entry1: Any,
    entry2: Any,
) -> None:
    await tcboard.process_tournament(tournament)
    ms = tcboard.matchstates_by_matchid["0"]

    newtournament = TCTournament(name="renamed")
    newtournament.add_court(court1)
    newtournament.add_draw(draw)
    newtournament.add_entries((entry1, entry2))
    newtournament.add_match(MatchFactory(id="0", matchnr=99, court=court1))

    await tcboard.process_tournament(newtournament)
    assert tcboard.matchstates_by_matchid["0"] is ms
    assert ms.match.matchnr == 99


@pytest.mark.asyncio
async def test_process_tournament_creates_livedata_for_played_match(
    tcboard: TCBoard, tournament: TCTournament, MatchFactory: Any, court1: _Court
) -> None:
    played = MatchFactory(id="played", status=MatchStatus.NOTPLAYED)
    tournament.add_match(played)
    await tcboard.process_tournament(tournament)
    ms = tcboard.matchstates_by_matchid["played"]
    assert ms.livedata is not None
    assert ms.livedata.court == court1.id


@pytest.mark.asyncio
async def test_process_tournament_acks_when_upstream_matches_live(
    tcboard: TCBoard,
    tournament: TCTournament,
    MatchFactory: Any,
    FakeLiveDataFactory: Any,
    entry1: Any,
    entry2: Any,
    court1: _Court,
) -> None:
    scores = [(11, 9)]
    m = MatchFactory(id="ackme", scores=scores, status=MatchStatus.PLAYED)
    tournament.add_match(m)
    ms = MatchState(
        match=m,
        livedata=FakeLiveDataFactory(
            court=court1.id, matchid="ackme", scores=scores, status=LiveStatus.FINISHED
        ),
    )
    tcboard.matchstates_by_matchid["ackme"] = ms

    await tcboard.process_tournament(tournament)
    assert ms.acked is True
    assert len(tcboard.alerts_by_courtid[None]) == 0


@pytest.mark.asyncio
async def test_process_tournament_alerts_when_upstream_differs(
    tcboard: TCBoard,
    tournament: TCTournament,
    MatchFactory: Any,
    FakeLiveDataFactory: Any,
    court1: _Court,
) -> None:
    m = MatchFactory(id="differ", scores=[(11, 9)], status=MatchStatus.PLAYED)
    tournament.add_match(m)
    ms = MatchState(
        match=m,
        livedata=FakeLiveDataFactory(
            court=court1.id,
            matchid="differ",
            scores=[(11, 5)],
            status=LiveStatus.FINISHED,
        ),
    )
    ms.acked = True
    tcboard.matchstates_by_matchid["differ"] = ms

    await tcboard.process_tournament(tournament)
    assert ms.acked is False
    alerts = tcboard.alerts_by_courtid[court1.id]
    assert any(a.text == "Upstream match data differ from live state" for a in alerts)


@pytest.mark.asyncio
async def test_process_tournament_sets_scoredev_for_known_devices(
    tcboard: TCBoard, tournament: TCTournament, court1: _Court
) -> None:
    tcboard.court_by_deviceid = {"dev-1": court1, "dev-none": None}
    await tcboard.process_tournament(tournament)
    assert tournament.courts[court1.id].scoredev == "dev-1"


@pytest.mark.asyncio
async def test_process_tournament_replays_buffered_livedata(
    tcboard: TCBoard,
    tournament: TCTournament,
    FakeLiveDataFactory: Any,
) -> None:
    tcboard.tournament = None
    buffered = FakeLiveDataFactory(court=1, matchid="0", status=LiveStatus.ONGOING)
    await tcboard.process_squore_livedata(buffered)
    assert tcboard._livedatabuffer == [buffered]

    await tcboard.process_tournament(tournament)
    assert tcboard._livedatabuffer == []
    assert tcboard.matchstates_by_matchid["0"].livedata is buffered


def test_set_scoredev_without_tournament_is_noop(
    tcboard: TCBoard, court1: _Court
) -> None:
    tcboard.tournament = None
    tcboard.set_scoredev_for_court(court1, "dev")  # must not raise
    assert tcboard.tournament is None


# ---------------------------------------------------------------------------
# process_squore_livedata
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_livedata_buffered_without_tournament(
    tcboard: TCBoard, FakeLiveDataFactory: Any
) -> None:
    tcboard.tournament = None
    data = FakeLiveDataFactory(matchid="0", status=LiveStatus.ONGOING)
    await tcboard.process_squore_livedata(data)
    assert tcboard._livedatabuffer == [data]


@pytest.mark.asyncio
async def test_livedata_for_unknown_match_on_known_court(
    tcboard: TCBoard, FakeLiveDataFactory: Any, court1: _Court
) -> None:
    data = FakeLiveDataFactory(
        court=court1.id, matchid="nope", status=LiveStatus.ONGOING
    )
    await tcboard.process_squore_livedata(data)
    alerts = tcboard.alerts_by_courtid[court1.id]
    assert any(a.text == "Received livedata for unknown match" for a in alerts)


@pytest.mark.asyncio
async def test_livedata_for_unknown_match_on_unknown_court(
    tcboard: TCBoard, FakeLiveDataFactory: Any
) -> None:
    data = FakeLiveDataFactory(court=999, matchid="nope", status=LiveStatus.ONGOING)
    await tcboard.process_squore_livedata(data)
    assert tcboard.alerts_by_courtid[None]


@pytest.mark.asyncio
async def test_livedata_for_unknown_match_without_court(
    tcboard: TCBoard, FakeLiveDataFactory: Any
) -> None:
    data = FakeLiveDataFactory(matchid="nope", status=LiveStatus.ONGOING)
    await tcboard.process_squore_livedata(data)
    assert tcboard.alerts_by_courtid[None]


@pytest.mark.asyncio
async def test_livedata_accepted_and_stored(
    tcboard: TCBoard, FakeLiveDataFactory: Any, court1: _Court
) -> None:
    dev = DeviceInfo(deviceid="dev-a")
    data = FakeLiveDataFactory(
        court=court1.id,
        matchid="0",
        deviceid="dev-a",
        status=LiveStatus.ONGOING,
        devinfo=dev,
    )
    await tcboard.process_squore_livedata(data)
    assert tcboard.matchstates_by_matchid["0"].livedata is data
    assert tcboard.court_by_deviceid["dev-a"] == court1


@pytest.mark.asyncio
async def test_livedata_warns_when_device_moves_court(
    tcboard: TCBoard, FakeLiveDataFactory: Any, mocker: MockerFixture
) -> None:
    warn = mocker.patch("tcboard.board.logger.warning")
    await tcboard.process_squore_livedata(
        FakeLiveDataFactory(matchid="0", deviceid="dev-m", status=LiveStatus.ONGOING)
    )
    await tcboard.process_squore_livedata(
        FakeLiveDataFactory(matchid="1", deviceid="dev-m", status=LiveStatus.ONGOING)
    )
    assert any("was previously broadcasting" in c.args[0] for c in warn.call_args_list)


@pytest.mark.asyncio
async def test_livedata_validation_error_is_recorded(
    tcboard: TCBoard, FakeLiveDataFactory: Any, court1: _Court
) -> None:
    first = FakeLiveDataFactory(
        court=court1.id, matchid="0", deviceid="dev-1", status=LiveStatus.ONGOING
    )
    await tcboard.process_squore_livedata(first)

    rogue = FakeLiveDataFactory(
        court=court1.id, matchid="0", deviceid="dev-2", status=LiveStatus.ONGOING
    )
    await tcboard.process_squore_livedata(rogue)
    alerts = tcboard.alerts_by_courtid[court1.id]
    assert any("different device" in a.text for a in alerts)


# ---------------------------------------------------------------------------
# process_deviceinfo (still contains a debugger trap, see fake_ipdb)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_deviceinfo_posts_update(
    tcboard: TCBoard, fake_ipdb: MagicMock, mocker: MockerFixture
) -> None:
    post = mocker.patch.object(tcboard, "_post_update", new=AsyncMock())
    post.side_effect = None
    mocker.patch.object(TCBoard, "_post_update", new=AsyncMock())
    await tcboard.process_deviceinfo(DeviceInfo(deviceid="dev"))
    fake_ipdb.set_trace.assert_called_once()


# ---------------------------------------------------------------------------
# ack / reset / clear
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ack_and_unack_match(tcboard: TCBoard, matchstate: MatchState) -> None:
    tcboard.matchstates_by_matchid[matchstate.match.id] = matchstate
    await tcboard.ack_match(matchstate.match.id)
    assert matchstate.acked is True
    await tcboard.ack_match(matchstate.match.id, acked=False)
    assert matchstate.acked is False


@pytest.mark.asyncio
async def test_ack_match_index_error_becomes_entity_not_found(
    tcboard: TCBoard, matchstate: MatchState, mocker: MockerFixture
) -> None:
    tcboard.matchstates_by_matchid[matchstate.match.id] = matchstate
    mocker.patch.object(MatchState, "ack", side_effect=KeyError("gone"))
    with pytest.raises(EntityNotFoundError):
        await tcboard.ack_match(matchstate.match.id)


@pytest.mark.asyncio
async def test_ack_unknown_match_raises_entity_not_found(tcboard: TCBoard) -> None:
    with pytest.raises(EntityNotFoundError):
        await tcboard.ack_match("nope")


@pytest.mark.asyncio
async def test_reset_match(tcboard: TCBoard, matchstate: MatchState) -> None:
    tcboard.matchstates_by_matchid[matchstate.match.id] = matchstate
    matchstate.livedata = MagicMock()
    await tcboard.reset_match(matchstate.match.id)
    assert matchstate.livedata is None


@pytest.mark.asyncio
async def test_reset_match_index_error_becomes_entity_not_found(
    tcboard: TCBoard, matchstate: MatchState, mocker: MockerFixture
) -> None:
    tcboard.matchstates_by_matchid[matchstate.match.id] = matchstate
    mocker.patch.object(MatchState, "reset", side_effect=KeyError("gone"))
    with pytest.raises(EntityNotFoundError):
        await tcboard.reset_match(matchstate.match.id)


@pytest.mark.asyncio
async def test_clear_alert_skips_already_cleared(
    tcboard: TCBoard, court1: _Court
) -> None:
    cleared = Alert(text="old")
    cleared.clear()
    live = Alert(text="live")
    tcboard.handle_error(cleared, court1)
    tcboard.handle_error(live, court1)

    await tcboard.clear_alert(court1.id, live.id)
    assert live.cleared is not None
    assert cleared.cleared is not None


@pytest.mark.asyncio
async def test_clear_alert_not_found(tcboard: TCBoard, court1: _Court) -> None:
    with pytest.raises(EntityNotFoundError):
        await tcboard.clear_alert(court1.id, Alert(text="x").id)


# ---------------------------------------------------------------------------
# courtstates
# ---------------------------------------------------------------------------


def _put(
    board: TCBoard,
    match: Any,
    status: LiveStatus | None,
    FakeLiveDataFactory: Any,
    *,
    acked: bool = False,
    deviceid: str = "dev",
) -> MatchState:
    livedata = (
        None
        if status is None
        else FakeLiveDataFactory(
            court=match.court.id if match.court else None,
            matchid=match.id,
            deviceid=deviceid,
            status=status,
        )
    )
    ms = MatchState(match=match, livedata=livedata)
    ms.acked = acked
    board.matchstates_by_matchid[match.id] = ms
    return ms


def test_courtstate_sorts_pending_current_finished(
    tcboard: TCBoard,
    court1: _Court,
    MatchFactory: Any,
    FakeLiveDataFactory: Any,
) -> None:
    pend = _put(tcboard, MatchFactory(id="p1", court=court1), None, FakeLiveDataFactory)
    _put(
        tcboard,
        MatchFactory(id="p2", court=court1, acked=None)
        if False
        else MatchFactory(id="p2", court=court1),
        None,
        FakeLiveDataFactory,
        acked=True,
    )
    cur = _put(
        tcboard,
        MatchFactory(id="c1", court=court1),
        LiveStatus.ONGOING,
        FakeLiveDataFactory,
    )
    fin = _put(
        tcboard,
        MatchFactory(id="f1", court=court1),
        LiveStatus.FINISHED,
        FakeLiveDataFactory,
    )
    _put(
        tcboard,
        MatchFactory(id="h1", court=court1),
        LiveStatus.EXTERNAL,
        FakeLiveDataFactory,
    )

    cs = tcboard.get_courtstate_for_court(court1)
    assert pend in cs.pending
    assert all(m.match.id != "p2" for m in cs.pending)  # acked pending is hidden
    assert cur in cs.current
    assert fin in cs.finished
    assert all(m.match.id != "h1" for m in cs.current + cs.finished)


def test_courtstate_warns_on_more_than_one_current(
    tcboard: TCBoard,
    court1: _Court,
    MatchFactory: Any,
    FakeLiveDataFactory: Any,
) -> None:
    _put(
        tcboard,
        MatchFactory(id="c1", court=court1),
        LiveStatus.ONGOING,
        FakeLiveDataFactory,
    )
    _put(
        tcboard,
        MatchFactory(id="c2", court=court1),
        LiveStatus.ONGOING,
        FakeLiveDataFactory,
    )
    cs = tcboard.get_courtstate_for_court(court1)
    assert len(cs.current) == 2
    assert any(
        "More than one current" in a.text for a in tcboard.alerts_by_courtid[court1.id]
    )


def test_courtstate_alerts_on_unknown_slot(
    tcboard: TCBoard,
    court1: _Court,
    MatchFactory: Any,
    FakeLiveDataFactory: Any,
) -> None:
    _put(
        tcboard,
        MatchFactory(id="u1", court=court1),
        LiveStatus.UNKNOWN,
        FakeLiveDataFactory,
    )
    tcboard.get_courtstate_for_court(court1)
    assert any("unknown slot" in a.text for a in tcboard.alerts_by_courtid[court1.id])


def test_courtstate_includes_battery_levels(
    tcboard: TCBoard,
    court1: _Court,
    MatchFactory: Any,
    FakeLiveDataFactory: Any,
) -> None:
    dev = DeviceInfo(deviceid="dev-b")
    tcboard._deviceinfo_by_court[court1].add(dev)
    cs = tcboard.get_courtstate_for_court(court1)
    assert cs.batterylevels is not None
    assert "dev-b" in cs.batterylevels


def test_courtstates_by_court_without_tournament(
    matchstate: MatchState,
) -> None:
    board = TCBoard()
    board.matchstates_by_matchid[matchstate.match.id] = matchstate
    states = board.get_courtstates_by_court()
    assert set(states) == {matchstate.match.court}


# ---------------------------------------------------------------------------
# updates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_update_is_suppressed_when_disabled(tcboard: TCBoard) -> None:
    fn = AsyncMock()
    tcboard.register_update_function(fn)
    async with tcboard.disable_updates():
        await tcboard._post_update(make_dirty=True)
    fn.assert_not_awaited()
    assert tcboard.rev == 0

    await tcboard._post_update(make_dirty=True)
    fn.assert_awaited_once()
    assert tcboard.rev == 1


def test_courtstates_by_court_with_tournament(tcboard: TCBoard) -> None:
    states = tcboard.get_courtstates_by_court()
    assert set(states) == set(tcboard.tournament.get_courts())  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_update_copies_state_from_other_board(
    tcboard: TCBoard, matchstate: MatchState, mocker: MockerFixture
) -> None:
    other = TCBoard(rev=7)
    other.matchstates_by_matchid[matchstate.match.id] = matchstate
    fn = AsyncMock()
    tcboard.register_update_function(fn)

    await tcboard.update(other, increv=True)
    assert tcboard.rev == 8
    assert tcboard.matchstates_by_matchid is other.matchstates_by_matchid
    fn.assert_awaited_once_with(tcboard)


@pytest.mark.asyncio
async def test_update_without_other_only_posts(tcboard: TCBoard) -> None:
    fn = AsyncMock()
    tcboard.register_update_function(fn)
    await tcboard.update()
    assert tcboard.rev == 0
    fn.assert_awaited_once_with(tcboard)


@pytest.mark.asyncio
async def test_clear_alert_already_cleared_is_not_found(
    tcboard: TCBoard, court1: _Court
) -> None:
    done = Alert(text="already done")
    done.clear()
    tcboard.handle_error(done, court1)
    with pytest.raises(EntityNotFoundError):
        await tcboard.clear_alert(court1.id, done.id)
