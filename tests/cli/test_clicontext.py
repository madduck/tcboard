from click_async_plugins import ITC

from tcboard.cli.util import CliContext


def test_constructor(itc: ITC) -> None:
    clictx = CliContext(itc=itc)
    assert clictx.api.state.clictx is clictx
