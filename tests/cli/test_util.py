from click_async_plugins import ITC
from pytest_mock import MockType

from tcboard.cli.util import CliContext


def test_get_clictx_api_roundtrip(itc: ITC, httpcon: MockType) -> None:
    clictx = CliContext(itc=itc, api=httpcon.app)
    assert clictx is httpcon.app.state.clictx
