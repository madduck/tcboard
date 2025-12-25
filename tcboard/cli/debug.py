import logging
import math
import sys
from contextlib import asynccontextmanager
from functools import partial
from typing import Any

from click_async_plugins import PluginLifespan, plugin
from click_async_plugins.debug import (
    KeyAndFunc,
    KeyCmdMapType,
    monitor_stdin_for_debug_commands,
)
from tptools.util import nonblocking_write

from .util import CliContext, pass_clictx

logger = logging.getLogger(__name__)


def list_connections(_: CliContext) -> str | None:
    """List open connections"""
    ret = "Open connections:"

    conns: list[Any] = []
    if (nconn := len(conns)) == 0:
        return f"{ret} (none)"
    else:
        ret += "\n"
    maxlen = math.ceil(math.log(nconn) / math.log(10))
    ret += "\n".join(f"  {i:{maxlen}d}. {conn}" for i, conn in enumerate(conns, 1))
    return ret


@asynccontextmanager
async def debug_key_press_handler(clictx: CliContext) -> PluginLifespan:
    key_to_cmd: KeyCmdMapType[CliContext] = {
        0x0C: KeyAndFunc("^L", list_connections),
    }
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
