import asyncio
import logging
import os
import pathlib
import sys
import warnings
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager
from functools import partial
from typing import Literal

from click_async_plugins import (
    ITC,
    PluginFactory,
    create_plugin_task,
    setup_plugins,
)
from fastapi import FastAPI
from httpx2 import URL
from tptools.util import is_truish, silence_logger

from tcboard.board import TCBoard
from tcboard.cli.api import configure_api
from tcboard.cli.db import database_backend
from tcboard.cli.debug import debug_key_press_handler
from tcboard.cli.main import (
    make_app,
    on_board_update,
    process_squore_livedata,
    receive_tournament,
)
from tcboard.cli.tptools import setup_for_tptools
from tcboard.cli.util import CliContext

logging.getLogger().setLevel(logging.DEBUG)

if not sys.warnoptions:
    warnings.simplefilter("default")
    logging.captureWarnings(True)


THIRD_PARTY_LOG_LEVELS = [
    ("asyncio", logging.INFO),
    ("aiosqlite", logging.INFO),
    ("watchfiles", logging.WARNING),
    ("uvicorn", logging.INFO),
    ("uvicorn.error", logging.WARNING),
    ("click_async_plugins", logging.DEBUG),
    ("httpcore2", logging.INFO),
    ("httpx2", logging.INFO),
]

if is_truish(os.getenv("LESS_DEBUG", os.getenv("LESSDEBUG"))):
    LOG_LEVELS = [
        (__name__, logging.INFO),
        ("tptools", logging.INFO),
        ("tcboard.cli", logging.INFO),
        ("tcboard.dbmanager", logging.INFO),
        ("tcboard.board", logging.INFO),
    ]
else:
    LOG_LEVELS = []

for name, level in LOG_LEVELS + THIRD_PARTY_LOG_LEVELS:
    silence_logger(name, level=level)

logger = logging.getLogger(__name__)


DB_FILE: pathlib.Path | Literal[":memory:"] | None
if (envfile := os.getenv("DB", os.getenv("DB_FILE"))) is None:
    DB_FILE = pathlib.Path(__file__).parent / "db.sqlite"

elif envfile == ":memory:":
    DB_FILE = None

else:
    DB_FILE = pathlib.Path(envfile)

database_backend = partial(database_backend, file=DB_FILE)

debug_match_ids: list[str] = []
if dmis := os.getenv("DEBUG_MATCH_IDS", ""):
    debug_match_ids = dmis.split(",")


@asynccontextmanager
async def app_lifespan(api: FastAPI) -> AsyncGenerator[None]:
    board = TCBoard(debug_match_ids=debug_match_ids)
    itc = ITC()
    itc.set("board", board)

    clictx = CliContext(api=api, itc=itc)

    board.register_update_function(partial(on_board_update, itc=itc))

    BOOTSTRAP_URL = os.getenv("BOOTSTRAP_URL")
    tptools = partial(
        setup_for_tptools,
        load_from_url=None if BOOTSTRAP_URL is None else URL(BOOTSTRAP_URL),
    )

    factories: list[PluginFactory] = [
        debug_key_press_handler,
        database_backend,
        tptools,
        receive_tournament,
        process_squore_livedata,
        configure_api,
    ]

    try:
        async with AsyncExitStack() as stack:
            tasks = await setup_plugins(factories, stack=stack, clictx=clictx)

            try:
                async with asyncio.TaskGroup() as tg:
                    plugin_task = partial(
                        create_plugin_task, create_task_fn=tg.create_task
                    )
                    for task in tasks:
                        plugin_task(task)
                    logger.debug("Tasks:")
                    for t in tg._tasks:
                        logger.debug(f"  {t}")
                    yield
                    raise asyncio.CancelledError

            except asyncio.CancelledError:
                logger.info("Exiting…")

    except* RuntimeError:
        logger.exception("A runtime error occurred")

    except* Exception as exc:
        import ipdb

        logger.exception("")
        ipdb.set_trace()  # noqa: E402 E702 I001 # fmt: skip
        _ = exc


app = make_app(lifespan=app_lifespan)
