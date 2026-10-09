import asyncio
import importlib
import importlib.resources
import logging
import pathlib
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager
from functools import partial
from typing import Any, Never, cast

import click
import click_extra as clickx
import uvicorn
from click_async_plugins import (
    ITC,
    PluginFactory,
    PluginLifespan,
    create_plugin_task,
    plugin_group,
    react_to_data_update,
    setup_plugins,
)
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import (
    FileResponse,
    PlainTextResponse,
)
from starlette.status import HTTP_404_NOT_FOUND
from starlette.types import StatefulLifespan, StatelessLifespan
from tptools import VERSION as TPTOOLS_VERSION
from tptools.util import silence_logger

from tcboard import VERSION, TCBoard, TCTournament
from tcboard.devinfo import DeviceInfo
from tcboard.ext.squore.livedata import SquoreMatchLiveData

from .util import CliContext, pass_clictx

PLUGINS = ["debug", "tptools", "api", "db", "squoremqtt"]

try:
    from uvloop import new_event_loop

except ImportError:
    from asyncio import new_event_loop  # type: ignore[assignment]

logger = clickx.new_logger(
    format="{asctime} {name} {levelname} {message} ({filename}:{lineno})",
    datefmt="%F %T",
    level=logging.WARNING,
)


def _pong(request: Request) -> str:
    client = request.headers.get(
        "X-Forwarded-For", request.client.host if request.client else None
    )
    return (
        f"Hello {client}, tcboard {VERSION} is running "
        f"(with tptools {TPTOOLS_VERSION})!\n"
    )


def _favicon() -> FileResponse:
    with importlib.resources.path("tcboard", "assets", "favicon.ico") as favicon:
        return FileResponse(
            favicon,
            media_type="image/png",
        )


def _robotstxt() -> str:
    return "User-agent: *\nDisallow: /\n"


def dump_board(request: Request) -> Response:
    clictx: CliContext = request.app.state.clictx
    return Response(clictx.board.model_dump_json(), media_type="application/json")


def dump_match(request: Request, matchid: str) -> Response:
    clictx: CliContext = request.app.state.clictx
    if (m := clictx.board.matchstates_by_matchid.get(matchid)) is None:
        raise HTTPException(HTTP_404_NOT_FOUND, f"No match found with ID {matchid}")
    else:
        return Response(m.model_dump_json(), media_type="application/json")


def make_app(
    lifespan: StatelessLifespan[FastAPI] | StatefulLifespan[FastAPI] | None = None,
    *,
    app_class: type[FastAPI] = FastAPI,
) -> FastAPI:
    app = app_class(lifespan=lifespan)

    app.get("/", response_class=PlainTextResponse, name="root")(_pong)
    app.get("/favicon.ico", response_class=FileResponse)(_favicon)
    app.get("/robots.txt", response_class=PlainTextResponse)(_robotstxt)
    app.get("/debug/board", response_class=Response)(dump_board)
    app.get("/debug/match/{matchid}", response_class=Response)(dump_match)

    return app


@asynccontextmanager
async def receive_tournament(clictx: CliContext) -> PluginLifespan:
    updates_gen = cast(
        AsyncGenerator[TCTournament],
        clictx.itc.updates("tournament", yield_immediately=True),
    )
    yield react_to_data_update(updates_gen, callback=clictx.board.process_tournament)


@asynccontextmanager
async def process_squore_livedata(clictx: CliContext) -> PluginLifespan:
    updates_gen = cast(
        AsyncGenerator[SquoreMatchLiveData],
        clictx.itc.updates("squorelivedata", yield_immediately=True),
    )
    yield react_to_data_update(
        updates_gen, callback=clictx.board.process_squore_livedata
    )


@asynccontextmanager
async def process_squore_devinfo(clictx: CliContext) -> PluginLifespan:
    updates_gen = cast(
        AsyncGenerator[DeviceInfo],
        clictx.itc.updates("squoredevinfo", yield_immediately=True),
    )
    yield react_to_data_update(updates_gen, callback=clictx.board.process_deviceinfo)


boardlogger = logging.getLogger(__name__ + ".board")


async def on_board_update(board: TCBoard, itc: ITC, **updates: Any) -> None:
    itc.set("board", board)
    boardlogger.info("\n" + board.debug_render() + "\n")


@plugin_group
@clickx.config_option(
    strict=True,
    show_default=True,
    file_format_patterns=clickx.ConfigFormat.TOML,
    default=pathlib.Path(click.get_app_dir("tcboard")) / "cfg.toml",
)
@clickx.verbose_option(default_logger=logger)
@click.option("--very-debug", is_flag=True, help="Do not silence any debug logging")
@click.option(
    "--host",
    "-h",
    metavar="IP",
    default="0.0.0.0",
    show_default=True,
    help="Host to listen on (bind to)",
)
@click.option(
    "--port",
    "-p",
    metavar="PORT",
    type=click.IntRange(min=1024, max=65535),
    default=8001,
    show_default=True,
    help="Port to listen on",
)
@click.option(
    "--debug-match-id",
    "-d",
    "debug_match_ids",
    multiple=True,
    metavar="MATCHID",
    help="Match ID to debug",
)
@click.pass_context
def tcboard(
    ctx: click.Context,
    very_debug: bool,
    host: str,
    port: int,
    debug_match_ids: list[str],
) -> None:
    """Collect tournament data and distribute to subscribers"""

    if not very_debug:
        for name, level in (
            ("asyncio", logging.WARNING),
            ("click_extra", logging.INFO),
        ):
            silence_logger(name, level=level)

    # the options will be used in the result_callback function down below
    _ = host, port
    itc = ITC()
    board = TCBoard(debug_match_ids=debug_match_ids)
    board.register_update_function(partial(on_board_update, itc=itc))
    itc.set("board", board)

    app = make_app()

    ctx.obj = CliContext(api=app, itc=itc)
    app.state.clictx = ctx.obj


for plugin in PLUGINS:
    try:
        mod = importlib.import_module(f".{plugin}", __package__)

    except (ImportError, NotImplementedError) as exc:
        logger.warning(f"Plugin '{plugin}' cannot be loaded: {exc}")

    else:
        subcmd = getattr(mod, plugin)
        tcboard.add_command(subcmd)
        logger.debug(f"Added plugin to tcboard: {plugin}")


@tcboard.result_callback()
@pass_clictx
def runit(
    clictx: CliContext,
    plugin_factories: list[PluginFactory],
    very_debug: bool,
    host: str,
    port: int,
    debug_match_ids: list[int],
) -> Never:
    _ = very_debug, debug_match_ids

    loop = new_event_loop()
    asyncio.set_event_loop(loop)

    config = uvicorn.Config(clictx.api, host=host, port=port, access_log=False)
    server = uvicorn.Server(config)

    plugin_factories.append(partial(receive_tournament, clictx))
    plugin_factories.append(partial(process_squore_livedata, clictx))
    # plugin_factories.append(partial(process_squore_devinfo, clictx))

    # We do not use FastAPI's/Starlette's lifespan because of
    # https://github.com/fastapi/fastapi/discussions/13878
    # but handle the lifespan ourselves outside of the server process:
    async def lifespan(plugin_factories: list[PluginFactory]) -> None:
        async with AsyncExitStack() as stack:
            tasks = await setup_plugins(plugin_factories, stack=stack)

            try:
                async with asyncio.TaskGroup() as tg:
                    for task in tasks:
                        create_plugin_task(task, create_task_fn=tg.create_task)

                    try:
                        await server.serve()

                    except KeyboardInterrupt:
                        pass

                    raise asyncio.CancelledError

            except asyncio.CancelledError:
                logger.info("Exiting…")

    try:
        loop.run_until_complete(lifespan(plugin_factories))

    except* click.ClickException as exc:
        for e in exc.exceptions:
            raise e from exc

    except* Exception:
        import ipdb

        logger.exception("Something went really wrong")

        ipdb.set_trace()  # noqa: E402 E702 I001 # fmt: skip

        click.get_current_context().exit(1)

    click.get_current_context().exit(0)
