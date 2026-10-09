import asyncio
import logging
import pathlib
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import click
from aiosqlite import Cursor, Row
from click_async_plugins import PluginLifespan, plugin
from dateutil.parser import parser as dtparser
from tptools.util import silence_logger

from tcboard.ext.squore.livedata import SquoreMatchLiveData

from ..dbmanager import DBManager
from ..tournament import TCTournament
from .util import CliContext, pass_clictx

DEFAULT_SQLITE_PATH = pathlib.Path("./db.sqlite")

logger = logging.getLogger(__name__)

silence_logger("aiosqlite", level=logging.WARNING)


def _sqlite_dict_factory(cursor: Cursor, row: Row) -> dict[str, Any]:
    fields = [column[0] for column in cursor.description]
    return dict(zip(fields, row, strict=True))


# async def receive_updates(
#     clictx: CliContext,
#     record_tournaments: bool = True,
#     record_livedata: bool = True,
# ) -> None:
#     sources = []
#     if record_tournaments:
#         sources.append(clictx.itc.updates("tournament", yield_immediately=True))
#     if record_livedata:
#         sources.append(clictx.itc.updates("squorelivedata", yield_immediately=True))
#     if not sources:
#         return
#
#     clictx.dbmgr = cast(DBManager, clictx.dbmgr)
#     async with aiostream.stream.merge(*sources).stream() as events_gen:
#         async for event in events_gen:
#             if event is None:
#                 continue
#             elif isinstance(event, Tournament):
#                 await clictx.dbmgr.record_tournament(event)
#             elif isinstance(event, SquoreMatchLiveData):
#                 await clictx.dbmgr.record_squore_livedata(event)
#             else:
#                 logger.warning(
#                     "Received unexpected event "
#                     f"of type {event.__class__.__qualname__}: {event}"
#                 )
#
#


async def _replay_events(clictx: CliContext, db: DBManager, speed: float) -> None:
    ts_prev: datetime | None = None
    dtparse = dtparser().parse
    board = clictx.board
    alerts = board.alerts_by_courtid.copy()
    async for rec in db.get_all_tournament_and_livedata_records():
        ts = dtparse(rec["timestamp"])
        delay = ts - (ts_prev or ts)
        await asyncio.sleep(delay.total_seconds() / speed)

        logger.info(f"Replaying {rec['type']} @ {ts.isoformat()}")

        match rec["type"]:
            case "tournament":
                await board.process_tournament(
                    TCTournament.model_validate_json(rec["data"])
                )

            case "squorelivedata":
                await board.process_squore_livedata(
                    SquoreMatchLiveData.model_validate_json(rec["data"])
                )

        ts_prev = ts

        if board.alerts_by_courtid != alerts:
            import ipdb

            ipdb.set_trace()  # noqa: E402 E702 I001 # fmt: skip

        alerts = board.alerts_by_courtid.copy()


@asynccontextmanager
async def database_backend(
    clictx: CliContext,
    *,
    speed: float = 1,
    file: pathlib.Path = DEFAULT_SQLITE_PATH,
) -> PluginLifespan:
    async with DBManager(file=file) as dbmgr:
        yield _replay_events(clictx, dbmgr, speed)


@plugin
@click.option(
    "--file",
    "-f",
    metavar="SQLITE_DATABASE",
    default=DEFAULT_SQLITE_PATH,
    type=click.Path(path_type=pathlib.Path),
    show_default=True,
    help="SQLite database to persist events",
)
@click.option(
    "--speed",
    "-s",
    metavar="SPEEDUP_FACTOR",
    default=1,
    type=float,
    show_default=True,
    help="Factor to speed up replay if desired",
)
@pass_clictx
async def replay(
    clictx: CliContext,
    file: pathlib.Path,
    speed: float,
) -> PluginLifespan:
    """Replay events from database"""

    async with database_backend(
        clictx,
        file=file,
        speed=speed,
    ) as task:
        yield task
