import logging
import sys
from contextlib import asynccontextmanager
from functools import partial

from click_async_plugins import PluginLifespan, plugin
from click_async_plugins.debug import (
    KeyCmdMapType,
    monitor_stdin_for_debug_commands,
)
from tptools.util import nonblocking_write

from .util import CliContext, pass_clictx

logger = logging.getLogger(__name__)


@asynccontextmanager
async def debug_key_press_handler(clictx: CliContext) -> PluginLifespan:
    key_to_cmd: KeyCmdMapType[CliContext] = {}
    puts = partial(nonblocking_write, file=sys.stderr, eol="\n")
    async with monitor_stdin_for_debug_commands(
        clictx, key_to_cmd=key_to_cmd, puts=puts
    ) as task:
        yield task


@plugin
@pass_clictx
async def debug(clictx: CliContext) -> PluginLifespan:
    """Allow for debug-level interaction with the CLI"""

    async with debug_key_press_handler(clictx) as task:
        yield task
    key_to_cmd: KeyCmdMapType[CliContext] = {
        0x0C: KeyAndFunc("^L", list_connections),
    }
