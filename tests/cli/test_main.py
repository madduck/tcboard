import asyncio
import importlib
import pathlib
import sys
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import click
import pytest
from click.testing import CliRunner
from click_async_plugins import ITC
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture
from tptools import VERSION as TPTOOLS_VERSION

import tcboard.cli.main as main_module
from tcboard import VERSION, TCBoard, TCTournament
from tcboard.cli.main import (
    dump_board,
    dump_match,
    make_app,
    on_board_update,
    process_squore_devinfo,
    process_squore_livedata,
    receive_tournament,
    tcboard,
)
from tcboard.cli.util import CliContext
from tcboard.matchstate import MatchState

from .conftest import cancel, wait_until

FAVICON = pathlib.Path(main_module.__file__).parent.parent / "assets" / "favicon.ico"


@pytest.fixture
def app(clictx: CliContext) -> FastAPI:
    app = make_app()
    app.state.clictx = clictx
    return app


@pytest.fixture
def fake_ipdb(mocker: MockerFixture) -> MagicMock:
    fake = MagicMock(name="ipdb")
    mocker.patch.dict(sys.modules, {"ipdb": fake})
    return fake


@pytest.fixture
def fake_uvicorn(mocker: MockerFixture) -> Generator[dict[str, Any], None, None]:
    """Replace uvicorn so that `tcboard <plugins>` runs without a real socket."""
    config = mocker.patch("tcboard.cli.main.uvicorn.Config")
    server = MagicMock(name="Server")

    async def _serve() -> None:
        # give the plugin tasks a chance to start, as a real server would
        await asyncio.sleep(0.01)

    server.serve = AsyncMock(side_effect=_serve)
    mocker.patch("tcboard.cli.main.uvicorn.Server", return_value=server)

    created: list[asyncio.AbstractEventLoop] = []
    real_new_loop = asyncio.new_event_loop

    def _track_loop() -> asyncio.AbstractEventLoop:
        loop = real_new_loop()
        created.append(loop)
        return loop

    mocker.patch("tcboard.cli.main.new_event_loop", side_effect=_track_loop)
    yield {"config": config, "server": server}
    for loop in created:
        loop.close()
    asyncio.set_event_loop(None)


def failing_after_start(exc: BaseException) -> Any:
    async def _serve() -> None:
        await asyncio.sleep(0.01)
        raise exc

    return _serve


@contextmanager
def reloaded_main(blocked: list[str]) -> Generator[Any, None, None]:
    """Reload tcboard.cli.main with some modules made un-importable."""
    saved = {name: sys.modules.get(name) for name in blocked}
    try:
        for name in blocked:
            sys.modules[name] = None  # type: ignore[assignment]
        yield importlib.reload(main_module)
    finally:
        for name, mod in saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod
        importlib.reload(main_module)


# --- the root command (pre-existing) ------------------------------------


def test_cli(runner: CliRunner) -> None:
    result = runner.invoke(tcboard)
    assert result.exit_code == 2


# --- HTTP endpoints of make_app -----------------------------------------


def test_pong_uses_client_host() -> None:
    resp = TestClient(make_app()).get("/")
    assert resp.status_code == 200
    assert resp.text == (
        f"Hello testclient, tcboard {VERSION} is running "
        f"(with tptools {TPTOOLS_VERSION})!\n"
    )


def test_pong_uses_forwarded_for() -> None:
    resp = TestClient(make_app()).get("/", headers={"X-Forwarded-For": "192.0.2.5"})
    assert resp.text.startswith("Hello 192.0.2.5, ")


def test_pong_without_client_address() -> None:
    request = MagicMock()
    request.headers = {}
    request.client = None
    assert main_module._pong(request).startswith("Hello None, ")


def test_favicon(app: FastAPI) -> None:
    resp = TestClient(app).get("/favicon.ico")
    assert resp.status_code == 200
    assert resp.content == FAVICON.read_bytes()


def test_robots_txt(app: FastAPI) -> None:
    resp = TestClient(app).get("/robots.txt")
    assert resp.text == "User-agent: *\nDisallow: /\n"


def test_debug_board(app: FastAPI, clictx: CliContext) -> None:
    resp = TestClient(app).get("/debug/board")
    assert resp.status_code == 200
    assert resp.json()["rev"] == clictx.board.rev


def test_debug_match_found(
    app: FastAPI, clictx: CliContext, matchstate: MatchState
) -> None:
    clictx.board.matchstates_by_matchid[matchstate.match.id] = matchstate
    resp = TestClient(app).get(f"/debug/match/{matchstate.match.id}")
    assert resp.status_code == 200
    assert resp.json()["match"]["id"] == matchstate.match.id


def test_debug_match_not_found(app: FastAPI) -> None:
    resp = TestClient(app).get("/debug/match/nope")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "No match found with ID nope"


def test_dump_functions_called_directly(clictx: CliContext) -> None:
    app = FastAPI()
    app.state.clictx = clictx
    request = MagicMock()
    request.app = app
    assert dump_board(request).media_type == "application/json"
    with pytest.raises(Exception) as exc:
        dump_match(request, "nope")
    assert getattr(exc.value, "status_code", None) == 404


def test_make_app_uses_given_class_and_lifespan() -> None:
    class Sub(FastAPI):
        pass

    started: list[bool] = []

    @contextmanager
    def _lifespan_marker(_: FastAPI) -> Generator[None, None, None]:
        started.append(True)
        yield

    async def lifespan(app: FastAPI) -> Any:
        started.append(True)
        yield None

    app = make_app(lifespan=lifespan, app_class=Sub)
    assert type(app) is Sub
    with TestClient(app):
        pass
    assert started == [True]


# --- plugin-side data pumps ----------------------------------------------


@pytest.mark.asyncio
async def test_receive_tournament_forwards_updates_to_board(
    clictx: CliContext, mocker: MockerFixture
) -> None:
    process = mocker.patch.object(TCBoard, "process_tournament", new=AsyncMock())
    fresh = TCTournament(name="fresh")
    async with receive_tournament(clictx) as task:
        pump = asyncio.create_task(task)  # type: ignore[arg-type]
        clictx.itc.set("tournament", fresh)
        await wait_until(lambda: process.await_count > 0)
        await cancel(pump)
    process.assert_awaited_with(fresh)


@pytest.mark.asyncio
async def test_process_squore_livedata_forwards_updates_to_board(
    clictx: CliContext, mocker: MockerFixture
) -> None:
    process = mocker.patch.object(TCBoard, "process_squore_livedata", new=AsyncMock())
    sentinel = object()
    async with process_squore_livedata(clictx) as task:
        pump = asyncio.create_task(task)  # type: ignore[arg-type]
        clictx.itc.set("squorelivedata", sentinel)
        await wait_until(lambda: process.await_count > 0)
        await cancel(pump)
    process.assert_awaited_with(sentinel)


@pytest.mark.asyncio
async def test_process_squore_devinfo_forwards_updates_to_board(
    clictx: CliContext, mocker: MockerFixture, fake_ipdb: MagicMock
) -> None:
    process = mocker.patch.object(TCBoard, "process_deviceinfo", new=AsyncMock())
    sentinel = object()
    async with process_squore_devinfo(clictx) as task:
        pump = asyncio.create_task(task)  # type: ignore[arg-type]
        clictx.itc.set("squoredevinfo", sentinel)
        await wait_until(lambda: process.await_count > 0)
        await cancel(pump)
    process.assert_awaited_with(sentinel)


@pytest.mark.asyncio
async def test_on_board_update_publishes_board_on_itc(clictx: CliContext) -> None:
    itc = ITC()
    board = TCBoard()
    await on_board_update(board, itc=itc)
    assert itc.get("board") is board


# --- the group and runit (uvicorn stubbed) --------------------------------


def test_runs_plugins_and_exits_cleanly(
    runner: CliRunner, fake_uvicorn: dict[str, Any]
) -> None:
    result = runner.invoke(tcboard, ["api"])
    assert result.exit_code == 0, result.output
    fake_uvicorn["server"].serve.assert_awaited_once()


def test_passes_host_and_port_to_uvicorn(
    runner: CliRunner, fake_uvicorn: dict[str, Any]
) -> None:
    result = runner.invoke(
        tcboard, ["-v", "-v", "--very-debug", "-h", "127.0.0.1", "-p", "2000", "api"]
    )
    assert result.exit_code == 0, result.output
    kwargs = fake_uvicorn["config"].call_args.kwargs
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 2000


def test_keyboard_interrupt_is_a_clean_exit(
    runner: CliRunner, fake_uvicorn: dict[str, Any]
) -> None:
    fake_uvicorn["server"].serve.side_effect = failing_after_start(KeyboardInterrupt())
    result = runner.invoke(tcboard, ["api"])
    assert result.exit_code == 0, result.output


def test_unexpected_error_drops_into_debugger_and_exits_1(
    runner: CliRunner, fake_uvicorn: dict[str, Any], fake_ipdb: MagicMock
) -> None:
    fake_uvicorn["server"].serve.side_effect = failing_after_start(RuntimeError("boom"))
    result = runner.invoke(tcboard, ["api"])
    assert result.exit_code == 1
    fake_ipdb.set_trace.assert_called_once()


def test_click_exception_is_reraised(
    runner: CliRunner, fake_uvicorn: dict[str, Any]
) -> None:
    fake_uvicorn["server"].serve.side_effect = failing_after_start(
        click.ClickException("bad config")
    )
    result = runner.invoke(tcboard, ["api"])
    assert result.exit_code == 1
    assert "bad config" in result.output


def test_port_out_of_range_is_rejected(runner: CliRunner) -> None:
    result = runner.invoke(tcboard, ["-p", "80", "api"])
    assert result.exit_code == 2


# --- import-time fallbacks -----------------------------------------------


def test_falls_back_to_asyncio_loop_without_uvloop() -> None:
    with reloaded_main(["uvloop"]) as mod:
        assert mod.new_event_loop is asyncio.new_event_loop


def test_missing_plugin_is_skipped_with_warning() -> None:
    with reloaded_main(["tcboard.cli.debug"]) as mod:
        assert "debug" not in mod.tcboard.commands
        assert "api" in mod.tcboard.commands
