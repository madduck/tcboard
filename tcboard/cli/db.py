import logging
import pathlib
from contextlib import asynccontextmanager
from os import PathLike
from typing import Any, Literal, cast

import aiostream
import click
from click_async_plugins import PluginLifespan, plugin
from tptools.util import silence_logger

from tcboard import TCBoard, TCTournament
from tcboard.ext.squore.livedata import SquoreMatchLiveData

from ..dbmanager import DBManager
from .util import CliContext, pass_clictx

DEFAULT_SQLITE_PATH = pathlib.Path("./db.sqlite")

logger = logging.getLogger(__name__)

silence_logger("aiosqlite", level=logging.WARNING)


async def receive_updates(
    clictx: CliContext,
    record_tournaments: bool = True,
    record_livedata: bool = True,
) -> None:
    sources = []
    if record_tournaments:
        sources.append(clictx.itc.updates("tournament", yield_immediately=True))
    if record_livedata:
        sources.append(clictx.itc.updates("squorelivedata", yield_immediately=True))
    if not sources:
        return

    clictx.dbmgr = cast(DBManager, clictx.dbmgr)
    async with aiostream.stream.merge(*sources).stream() as events_gen:
        async for event in events_gen:
            if event is None:
                continue
            elif isinstance(event, TCTournament):
                await clictx.dbmgr.record_tournament(event)
            elif isinstance(event, SquoreMatchLiveData):
                await clictx.dbmgr.record_livedata(event)
            else:
                logger.warning(
                    "Received unexpected event "
                    f"of type {event.__class__.__qualname__}: {event}"
                )


@asynccontextmanager
async def database_backend(
    clictx: CliContext,
    *,
    file: pathlib.Path | None = DEFAULT_SQLITE_PATH,
    record_tournament_data: bool = True,
    record_livedata: bool = True,
) -> PluginLifespan:
    async with DBManager(file=file) as db:
        logger.info(f"Opening database {file}")

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
                    import ipdb

                    ipdb.set_trace()  # noqa: E402 E702 I001 # fmt: skip
                    # check whether tournament is a TCTournament
                    await clictx.board.process_tournament(tournament)
                    should_notify = True
                    logger.info(f"Read tournament from database: {tournament!r}")

                cnt = 0
                async for ldjson in db.get_latest_livedata_json_for_each_match():
                    livedata = SquoreMatchLiveData.model_validate_json(ldjson)
                    await clictx.board.process_squore_livedata(livedata)
                    cnt += 1
                else:
                    should_notify = True
                    logger.info(f"Read {cnt} records of livedata from database")

            if should_notify:
                await clictx.board.update()

        async def record_board_state(board: TCBoard, **updates: Any) -> None:
            await db.record_board_state(board, **updates)

        from typing import Any, Callable, Coroutine

        from tcboard.board import UpdateCallable

        _a: Callable[[TCBoard], Coroutine[Any, Any, None]] = record_board_state
        _b: Callable[..., Coroutine[Any, Any, None]] = record_board_state
        _check: UpdateCallable = record_board_state
        clictx.board.register_update_function(record_board_state)

        yield receive_updates(
            clictx,
            record_tournaments=record_tournament_data,
            record_livedata=record_livedata,
        )

    logger.info(f"Closing database {file}")


class OptionalPath(click.Path):
    """A click.Path that accepts `false` from a config file to mean "not set".

    - bool False -> None (so your internal default can kick in)
    - bool True  -> usage error
    - anything else -> normal click.Path handling
    """

    def convert(  # type: ignore[override]
        self,
        value: str | PathLike[str] | bool,
        param: click.Parameter | None,
        ctx: click.Context | None,
    ) -> str | bytes | PathLike[str] | None:
        if isinstance(value, bool):
            if value is False:
                return None
            self.fail(
                "`true` is not a valid value here. Provide a file name, or use "
                "`false` to select the built-in default of an in-memory database",
                param,
                ctx,
            )
        return super().convert(value, param, ctx)


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
@pass_clictx
async def db(
    clictx: CliContext,
    file: pathlib.Path | Literal[False] | None,
    record_tournament_data: bool,
    record_livedata: bool,
) -> PluginLifespan:
    """Listen to live Squore match data on MQTT"""

    async with database_backend(
        clictx,
        file=file or None,
        record_tournament_data=record_tournament_data,
        record_livedata=record_livedata,
    ) as task:
        yield task
