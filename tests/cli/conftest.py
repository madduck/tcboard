import pytest
from click.testing import CliRunner
from click_async_plugins import ITC
from fastapi.requests import HTTPConnection
from pytest_mock import MockerFixture, MockType
from starlette.datastructures import MutableHeaders

from tcboard import TCBoard, TCTournament
from tcboard.cli.util import CliContext


@pytest.fixture
def httpcon(mocker: MockerFixture) -> MockType:
    httpcon = mocker.MagicMock(spec=HTTPConnection)
    httpcon.headers = MutableHeaders({})
    httpcon.client = None
    return httpcon


@pytest.fixture
def itc() -> ITC:
    return ITC()


@pytest.fixture
def tcboard(tournament: TCTournament) -> TCBoard:
    return TCBoard(tournament=tournament)


@pytest.fixture
def clictx(itc: ITC, tcboard: TCBoard) -> CliContext:
    itc.set("board", tcboard)
    return CliContext(itc)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()
