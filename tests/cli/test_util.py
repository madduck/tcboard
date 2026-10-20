import pathlib

import click
import pytest
from click_async_plugins import ITC
from fastapi import HTTPException
from fastapi.datastructures import Address, Headers
from pytest_mock import MockType
from starlette.status import HTTP_424_FAILED_DEPENDENCY
from tptools import Court

from tcboard import TCBoard, TCTournament
from tcboard.cli.util import (
    CliContext,
    OptionalPath,
    get_board,
    get_courts,
    get_remote,
    get_tournament,
)

# --- OptionalPath -----------------------------------------------------------


def test_optionalpath_false_means_unset() -> None:
    assert OptionalPath(path_type=pathlib.Path).convert(False, None, None) is None


def test_optionalpath_true_is_usage_error() -> None:
    with pytest.raises(click.BadParameter, match="`true` is not a valid value"):
        OptionalPath(path_type=pathlib.Path).convert(True, None, None)


def test_optionalpath_string_is_normal_path() -> None:
    ret = OptionalPath(path_type=pathlib.Path).convert("some/file.sqlite", None, None)
    assert ret == pathlib.Path("some/file.sqlite")


def test_get_remote(httpcon: MockType) -> None:
    assert "unknown" in get_remote(httpcon)

    httpcon.client = Address("localhost", 1234)
    assert get_remote(httpcon) == "localhost"

    httpcon.headers = Headers({"X-Forwarded-For": "192.0.2.1"})
    assert get_remote(httpcon) == "192.0.2.1"


def test_get_clictx_api_roundtrip(itc: ITC, httpcon: MockType) -> None:
    clictx = CliContext(itc=itc, api=httpcon.app)
    assert clictx is httpcon.app.state.clictx


def test_clictx_board_roundtrip(itc: ITC, tcboard: TCBoard) -> None:
    clictx = CliContext(itc)
    clictx.board = tcboard
    assert clictx.board is tcboard


def test_clictx_stores_itself_in_api_state(clictx: CliContext) -> None:
    assert clictx.api.state.clictx is clictx


def test_get_board(clictx: CliContext) -> None:
    assert isinstance(get_board(clictx), TCBoard)


def test_get_tournament(tcboard: TCBoard) -> None:
    assert isinstance(get_tournament(tcboard), TCTournament)


def test_get_tournament_raises_without_tournament() -> None:
    with pytest.raises(HTTPException) as exc:
        _ = get_tournament(TCBoard())
    assert exc.value.status_code == HTTP_424_FAILED_DEPENDENCY


def test_get_courts(court1: Court, tournament: TCTournament) -> None:
    assert court1 in get_courts(tournament)
