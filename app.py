import asyncio
import logging
import sys
import warnings
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager
from functools import partial

from click_async_plugins import ITC, PluginFactory, create_plugin_task, setup_plugins
from fastapi import FastAPI
from tptools.util import silence_logger

from tcboard.cli.debug import debug_key_press_handler
from tcboard.cli.main import make_app
from tcboard.cli.util import CliContext

logging.getLogger().setLevel(logging.DEBUG)

if not sys.warnoptions:
    warnings.simplefilter("default")
    logging.captureWarnings(True)

for name, level in (
    ("asyncio", logging.INFO),
    ("aiosqlite", logging.INFO),
    ("watchfiles.main", logging.WARNING),
    ("uvicorn.error", logging.WARNING),
    ("tptools.tpmatch", logging.INFO),
    ("click_async_plugins", logging.DEBUG),
):
    silence_logger(name, level=level)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def app_lifespan(api: FastAPI) -> AsyncGenerator[None]:
    itc = ITC()

    clictx = CliContext(api=api, itc=itc)

    factories: list[PluginFactory] = [
        debug_key_press_handler,
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
