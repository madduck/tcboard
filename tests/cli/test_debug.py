import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_mock import MockerFixture

from tcboard import TCBoard
from tcboard.alert import Alert
from tcboard.cli.debug import (
    clear_all_errors,
    close_websockets,
    debug,
    debug_key_press_handler,
    list_connections,
    list_court_devices,
    render_board,
    simulate_board_change,
)
from tcboard.cli.util import CliContext


@pytest.fixture
def fake_monitor(mocker: MockerFixture) -> MagicMock:
    @asynccontextmanager
    async def _fake(*_: Any, **__: Any) -> AsyncGenerator[str]:
        yield "monitor-task"

    return cast(
        MagicMock,
        mocker.patch(
            "tcboard.cli.debug.monitor_stdin_for_debug_commands", side_effect=_fake
        ),
    )


@pytest.mark.asyncio
async def test_simulate_board_change_bumps_rev(clictx: CliContext) -> None:
    rev = clictx.board.rev
    simulate_board_change(clictx)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert clictx.board.rev == rev + 1


def test_render_board(clictx: CliContext) -> None:
    rendered = render_board(clictx)
    assert isinstance(rendered, str)
    assert f"rev={clictx.board.rev}" in rendered


@pytest.mark.asyncio
async def test_clear_all_errors(clictx: CliContext) -> None:
    alert = Alert(text="something went wrong")
    clictx.board.handle_error(alert, court=None)
    assert alert.cleared is None

    clear_all_errors(clictx)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert alert.cleared is not None


@pytest.mark.asyncio
async def test_close_websockets_keeps_first_when_several(clictx: CliContext) -> None:
    wss = [MagicMock(disconnect=AsyncMock()) for _ in range(3)]
    clictx.websockets.extend(wss)

    close_websockets(clictx)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    wss[0].disconnect.assert_not_called()
    wss[1].disconnect.assert_awaited_once_with(reason="Force-close in debug mode")
    wss[2].disconnect.assert_awaited_once_with(reason="Force-close in debug mode")


@pytest.mark.asyncio
async def test_close_websockets_closes_only_one_if_only_one(
    clictx: CliContext,
) -> None:
    ws = MagicMock(disconnect=AsyncMock())
    clictx.websockets.append(ws)

    close_websockets(clictx)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    ws.disconnect.assert_awaited_once_with(reason="Force-close in debug mode")


def test_close_websockets_no_connections(clictx: CliContext) -> None:
    close_websockets(clictx)  # must not raise


def test_list_connections_none(clictx: CliContext) -> None:
    assert list_connections(clictx) == "Open connections: (none)"


def test_list_connections_mqtt_and_websockets(clictx: CliContext) -> None:
    clictx.mqttclients.add("mqtt-client-1")
    ws = MagicMock()
    ws.connstr = "ws-client-1"
    clictx.websockets.append(ws)

    ret = list_connections(clictx)
    assert ret is not None
    assert ret.startswith("Open connections:\n")
    assert "mqtt-client-1" in ret
    assert "ws-client-1" in ret
    assert "  1. " in ret
    assert "  2. " in ret


def test_list_connections_many_pads_numbers(clictx: CliContext) -> None:
    for i in range(10):
        clictx.mqttclients.add(f"conn-{i}")

    ret = list_connections(clictx)
    assert ret is not None
    assert " 1. conn-" in ret
    assert "10. conn-" in ret


def test_list_court_devices_no_tournament(itc: Any) -> None:
    clictx = CliContext(itc)
    clictx.itc.set("board", TCBoard())
    assert list_court_devices(clictx) == "Court devices: (none)"


def test_list_court_devices_no_devices_on_courts(clictx: CliContext) -> None:
    assert list_court_devices(clictx) == "Court devices: (none)"


def test_list_court_devices_lists_devices(clictx: CliContext) -> None:
    assert clictx.board.tournament is not None
    for court in clictx.board.tournament.courts.values():
        court.scoredev = f"dev-{court.id}"

    ret = list_court_devices(clictx)
    assert ret is not None
    assert "Court devices:\n" in ret
    assert "dev-1 on Court 1" in ret
    assert "dev-2 on Court 2" in ret


@pytest.mark.asyncio
async def test_debug_key_press_handler_registers_keys(
    clictx: CliContext, fake_monitor: MagicMock
) -> None:
    async with debug_key_press_handler(clictx):
        pass

    key_to_cmd = fake_monitor.call_args.kwargs["key_to_cmd"]
    assert set(key_to_cmd) == {0x02, 0x12, 0x17, 0x18, 0x0C, 0x16}
    assert key_to_cmd[0x02].key == "^B"
    assert key_to_cmd[0x12].func is simulate_board_change
    assert key_to_cmd[0x16].func is list_court_devices


@pytest.mark.asyncio
async def test_debug_plugin(run_plugin: Any, fake_monitor: MagicMock) -> None:
    async with run_plugin(debug) as task:
        assert task == "monitor-task"
    fake_monitor.assert_called_once()
