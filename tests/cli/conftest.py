import asyncio
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, cast
from unittest.mock import MagicMock

import click
import pytest
from click.testing import CliRunner
from click_async_plugins import ITC
from fastapi.requests import HTTPConnection
from pytest_mock import MockerFixture
from starlette.datastructures import MutableHeaders

from tcboard import TCBoard, TCTournament
from tcboard.cli.util import CliContext


@pytest.fixture
def httpcon(mocker: MockerFixture) -> MagicMock:
    httpcon = mocker.MagicMock(spec=HTTPConnection)
    httpcon.headers = MutableHeaders({})
    httpcon.client = None
    return cast(MagicMock, httpcon)


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


@asynccontextmanager
async def plugin_lifespan(
    cmd: click.Command, clictx: CliContext, args: list[str] | None = None
) -> AsyncGenerator[Any]:
    """Enter a plugin exactly as the CLI would: parse args, build the lifespan
    factory via PluginCommand.invoke(), then enter it within the click context
    so that pass_clictx can find the CliContext."""
    ctx = cmd.make_context(cmd.name or "", list(args or []), obj=clictx)
    with ctx:
        factory = cmd.invoke(ctx)
        async with factory() as task:
            yield task


@pytest.fixture
def run_plugin(clictx: CliContext) -> Callable[..., AbstractAsyncContextManager[Any]]:
    def _run(cmd: click.Command, args: list[str] | None = None) -> Any:
        return plugin_lifespan(cmd, clictx, args)

    return _run


async def wait_until(
    predicate: Callable[[], bool], timeout: float = 2.0, interval: float = 0.01
) -> None:
    """Poll until predicate() is true, yielding to the event loop in between."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(interval)


async def cancel(task: asyncio.Task[Any]) -> None:
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def close_if_coro(obj: Any) -> None:
    """Close coroutine objects yielded by plugins that we don't run."""
    if asyncio.iscoroutine(obj):
        obj.close()
