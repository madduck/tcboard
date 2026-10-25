import logging
import pathlib
from contextlib import asynccontextmanager
from typing import Any, Literal, cast

import aiostream
import click
from click_async_plugins import PluginLifespan, plugin
from tptools.util import silence_logger

from tcboard import TCBoard, TCTournament
from tcboard.devinfo import DeviceInfo
from tcboard.ext.squore.devinfo import SquoreDeviceInfo
from tcboard.ext.squore.livedata import SquoreMatchLiveData

from ..dbmanager import DBManager
from .util import CliContext, OptionalPath, pass_clictx

DEFAULT_SQLITE_PATH = pathlib.Path("./db.sqlite")

logger = logging.getLogger(__name__)

silence_logger("aiosqlite", level=logging.WARNING)


async def _handle_event(dbmgr: DBManager, event: Any) -> None:
    match event:
        case TCTournament():
            await dbmgr.record_tournament(event)
        case SquoreMatchLiveData():
            await dbmgr.record_livedata(event)
        case DeviceInfo():
            await dbmgr.record_devinfo(event)
        case None:
            pass
        case _:
            logger.warning(
                "Received unexpected event "
                f"of type {event.__class__.__qualname__}: {event}"
            )
    return


async def receive_updates(
    clictx: CliContext,
    record_tournaments: bool = True,
    record_livedata: bool = True,
    record_devinfo: bool = True,
) -> None:
    sources = []
    if record_tournaments:
        sources.append(clictx.itc.updates("tournament", yield_immediately=True))
    if record_livedata:
        sources.append(clictx.itc.updates("squorelivedata", yield_immediately=True))
    if record_devinfo:
        sources.append(clictx.itc.updates("squoredevinfo", yield_immediately=True))
    if not sources:
        return

    clictx.dbmgr = cast(DBManager, clictx.dbmgr)
    async with aiostream.stream.merge(*sources).stream() as events_gen:
        async for event in events_gen:
            await _handle_event(clictx.dbmgr, event)


@asynccontextmanager
async def database_backend(
    clictx: CliContext,
    *,
    file: pathlib.Path | None = DEFAULT_SQLITE_PATH,
    record_tournament_data: bool = True,
    record_livedata: bool = True,
    record_devinfo: bool = True,
) -> PluginLifespan:
    logger.info(f"Opening database {file}")
    async with DBManager(file=file) as db:
        clictx.dbmgr = db
        await db.init_tables()

        if (dbboard := await db.get_last_board()) is not None:
            await clictx.board.update(dbboard)
            logger.info(
                f"Initialised board for {dbboard.tournament} "
                f"from database (rev={dbboard.rev})"
            )

        else:
            should_notify = False
            async with clictx.board.disable_updates():
                if (tjson := await db.get_latest_tournament_json()) is not None:
                    tournament = TCTournament.model_validate_json(tjson)
                    await clictx.board.process_tournament(tournament)
                    should_notify = True
                    logger.info(f"Read tournament from database: {tournament!r}")

                cnt = 0
                async for ldjson in db.get_latest_livedata_json_for_each_match():
                    livedata = SquoreMatchLiveData.model_validate_json(ldjson)
                    await clictx.board.process_squore_livedata(livedata)
                    cnt += 1

                if cnt > 0:
                    should_notify = True
                    logger.info(f"Read {cnt} records of livedata from database")

                cnt = 0
                async for ldjson in db.get_latest_devinfo_json():
                    devinfo = SquoreDeviceInfo.model_validate_json(ldjson)
                    await clictx.board.process_squore_deviceinfo(devinfo)
                    cnt += 1

                if cnt > 0:
                    should_notify = True
                    logger.info(f"Read {cnt} records of devinfo from database")

            if should_notify:
                await clictx.board.update()

        async def record_board_state(board: TCBoard, **updates: Any) -> None:
            await db.record_board_state(board, **updates)

        clictx.board.register_update_function(record_board_state)

        yield receive_updates(
            clictx,
            record_tournaments=record_tournament_data,
            record_livedata=record_livedata,
            record_devinfo=record_devinfo,
        )

    logger.info(f"Closing database {file}")


@plugin
@click.option(
    "--file",
    "-f",
    metavar="SQLITE_DATABASE",
    default=DEFAULT_SQLITE_PATH,
    type=OptionalPath(path_type=pathlib.Path),
    show_default=True,
    help="SQLite database to persist events",
)
@click.option(
    "--record-tournament-data",
    is_flag=True,
    help="Record tournament data as it is received",
)
@click.option(
    "--record-livedata",
    is_flag=True,
    help="Record livedata data as it is received",
)
@click.option(
    "--record-devinfo",
    is_flag=True,
    help="Record device info data as it is received",
)
@pass_clictx
async def db(
    clictx: CliContext,
    file: pathlib.Path | Literal[False] | None,
    record_tournament_data: bool,
    record_livedata: bool,
    record_devinfo: bool,
) -> PluginLifespan:
    """Listen to live Squore match data on MQTT"""

    async with database_backend(
        clictx,
        file=file or None,
        record_tournament_data=record_tournament_data,
        record_livedata=record_livedata,
        record_devinfo=record_devinfo,
    ) as task:
        yield task
