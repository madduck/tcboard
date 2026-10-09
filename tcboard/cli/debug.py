import asyncio
import logging
import math
import sys
from contextlib import asynccontextmanager
from functools import partial

from click_async_plugins import PluginLifespan, plugin
from click_async_plugins.debug import (
    KeyAndFunc,
    KeyCmdMapType,
    monitor_stdin_for_debug_commands,
)
from tptools.util import nonblocking_write

from .util import CliContext, pass_clictx

logger = logging.getLogger(__name__)


def simulate_board_change(clictx: CliContext) -> None:
    """Simulate event that board was changed"""
    asyncio.create_task(clictx.board._post_update(make_dirty=True))
    # TODO: change when click_async_plugins supports coroutines


def render_board(clictx: CliContext) -> str:
    """Render a debug representation of TCBoard"""
    return clictx.board.debug_render()


def clear_all_errors(clictx: CliContext) -> None:
    """Acknowledge/clear all errors"""
    asyncio.create_task(clictx.board.clear_all_errors())


def list_connections(clictx: CliContext) -> str | None:
    """List open connections"""
    ret = "Open connections:"

    conns = list(clictx.mqttclients)
    if (nconn := len(conns)) == 0:
        return f"{ret} (none)"
    else:
        ret += "\n"
    maxlen = math.ceil(math.log(nconn) / math.log(10))
    ret += "\n".join(f"  {i:{maxlen}d}. {conn}" for i, conn in enumerate(conns, 1))
    return ret


def list_court_devices(clictx: CliContext) -> str | None:
    """List devices known to be on courts"""
    ret = "Court devices:"

    devs = (
        [(c, c.scoredev) for c in tournament.courts.values() if c.scoredev is not None]
        if (tournament := clictx.board.tournament) is not None
        else []
    )

    if (ndev := len(devs)) == 0:
        return f"{ret} (none)"
    else:
        ret += "\n"
    maxlen = math.ceil(math.log(ndev) / math.log(10))
    ret += "\n".join(
        f"  {i:{maxlen}d}. {d} on {c.name}" for i, (c, d) in enumerate(devs, 1)
    )
    return ret


@asynccontextmanager
async def debug_key_press_handler(clictx: CliContext) -> PluginLifespan:
    key_to_cmd: KeyCmdMapType[CliContext] = {
        0x02: KeyAndFunc("^B", render_board),
        0x12: KeyAndFunc("^R", simulate_board_change),
        0x18: KeyAndFunc("^X", clear_all_errors),
        0x0C: KeyAndFunc("^L", list_connections),
        0x16: KeyAndFunc("^V", list_court_devices),
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
