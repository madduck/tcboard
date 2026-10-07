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
