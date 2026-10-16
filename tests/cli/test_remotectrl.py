import asyncio
import json
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiomqtt import MqttError
from fastapi.datastructures import Address
from pytest_mock import MockerFixture

from tcboard import TCTournament
from tcboard.cli.remotectrl import (
    SQUORE_REMOTE_CONTROL_TOPIC,
    RemoteControlManager,
    SquoreMatchWithCourt,
    remote_control_loop,
    remote_control_publisher,
)
from tcboard.cli.remotectrl import (
    remotectrl as remotectrl_plugin,
)
from tcboard.cli.util import CliContext
from tcboard.ext.squore.livedata import SquoreMatchLiveData

from .conftest import cancel, close_if_coro, wait_until


class FakeClient:
    class _Paho:
        connect_timeout: float = 0.0

    def __init__(self) -> None:
        self.publish = AsyncMock()
        # aiomqtt stores the underlying paho client here; the handler sets its
        # connect timeout before connecting.
        self._client = self._Paho()

    async def __aenter__(self) -> "FakeClient":
        return self

    async def __aexit__(self, *_: Any) -> bool:
        return False


def _livedata(court: int | None, deviceid: str) -> MagicMock:
    ld = MagicMock(spec=SquoreMatchLiveData)
    ld.court = court
    ld.deviceid = deviceid
    return ld


# --- SquoreMatchWithCourt ---------------------------------------------------


def test_squorematchwithcourt_from_match_uses_court_id(match: Any) -> None:
    sm = SquoreMatchWithCourt.from_match(match)
    assert sm.court == match.court.id


def test_squorematchwithcourt_from_match_without_court(
    MatchFactory: Any,
) -> None:
    sm = SquoreMatchWithCourt.from_match(MatchFactory(court=None))
    assert sm.court is None


# --- RemoteControlManager ---------------------------------------------------


@pytest.mark.asyncio
async def test_manager_sends_when_match_put_on_court_with_known_device(
    tournament: TCTournament, match: Any, court1: Any
) -> None:
    mgr = RemoteControlManager()
    await mgr.receive_livedata(_livedata(court=court1.id, deviceid="dev-1"))

    court1.current_match = match
    callback = AsyncMock()
    await mgr.receive_tournament(tournament, callback)
    callback.assert_awaited_once_with(match, "dev-1")


@pytest.mark.asyncio
async def test_manager_warns_when_device_unknown(
    tournament: TCTournament, match: Any, court1: Any, mocker: MockerFixture
) -> None:
    warn = mocker.patch("tcboard.cli.remotectrl.logger.warning")
    mgr = RemoteControlManager()
    court1.current_match = match
    callback = AsyncMock()
    await mgr.receive_tournament(tournament, callback)
    callback.assert_not_awaited()
    assert "don't know the device ID" in warn.call_args.args[0]


@pytest.mark.asyncio
async def test_manager_does_not_resend_same_match(
    tournament: TCTournament, match: Any, court1: Any
) -> None:
    mgr = RemoteControlManager()
    await mgr.receive_livedata(_livedata(court=court1.id, deviceid="dev-1"))
    court1.current_match = match
    callback = AsyncMock()
    await mgr.receive_tournament(tournament, callback)
    await mgr.receive_tournament(tournament, callback)
    assert callback.await_count == 1


@pytest.mark.asyncio
async def test_manager_logs_when_court_cleared(
    tournament: TCTournament, match: Any, court1: Any, mocker: MockerFixture
) -> None:
    info = mocker.patch("tcboard.cli.remotectrl.logger.info")
    mgr = RemoteControlManager()
    court1.current_match = match
    await mgr.receive_tournament(tournament, AsyncMock())

    court1.current_match = None
    await mgr.receive_tournament(tournament, AsyncMock())
    assert any("cleared" in c.args[0] for c in info.call_args_list)


@pytest.mark.asyncio
async def test_manager_livedata_without_court_is_ignored() -> None:
    mgr = RemoteControlManager()
    await mgr.receive_livedata(_livedata(court=None, deviceid="dev-1"))
    assert mgr._courts_to_device_map == {}


# --- remote_control_loop ----------------------------------------------------


@pytest.mark.asyncio
async def test_remote_control_loop_publishes_match(
    clictx: CliContext,
    tournament: TCTournament,
    match: Any,
    court1: Any,
) -> None:
    client = FakeClient()
    clictx.itc.set("squorelivedata", _livedata(court=court1.id, deviceid="dev-9"))

    task = asyncio.create_task(
        remote_control_loop(
            clictx, cast(Any, client), "double-yellow/Squore/%c/remoteControl"
        )
    )
    # let the loop consume the initial livedata (device mapping) first
    await asyncio.sleep(0.05)
    court1.current_match = match
    clictx.itc.set("tournament", tournament)

    await wait_until(lambda: client.publish.await_count > 0)
    await cancel(task)

    assert client.publish.await_args is not None
    topic, payload = client.publish.await_args.args
    assert topic == "double-yellow/Squore/dev-9/remoteControl"
    assert json.loads(payload)["court"] == court1.id


@pytest.mark.asyncio
async def test_remote_control_loop_warns_on_unexpected_event(
    clictx: CliContext, mocker: MockerFixture
) -> None:
    warn = mocker.patch("tcboard.cli.remotectrl.logger.warning")
    clictx.itc.set("squorelivedata", "not-livedata")
    client = FakeClient()

    task = asyncio.create_task(
        remote_control_loop(clictx, cast(Any, client), SQUORE_REMOTE_CONTROL_TOPIC)
    )
    await wait_until(lambda: warn.called)
    await cancel(task)
    assert "unexpected event" in warn.call_args.args[0]
    client.publish.assert_not_awaited()


# --- remote_control_publisher ----------------------------------------------


@pytest.mark.asyncio
async def test_publisher_requires_mqtthost(clictx: CliContext) -> None:
    assert clictx.mqtthost is None
    with pytest.raises(ValueError, match="mqtthost is unset"):
        async with remote_control_publisher(clictx):
            pass


@pytest.mark.asyncio
async def test_publisher_yields_the_connect_loop(clictx: CliContext) -> None:
    clictx.mqtthost = Address("broker", 1883)

    async with remote_control_publisher(clictx, remotectrl_topic="t/%c") as task:
        # The connect loop must be deferred into the yielded task, so that
        # setup_plugins() cannot block on the MQTT connect.
        assert asyncio.iscoroutine(task)
        close_if_coro(task)


@pytest.mark.asyncio
async def test_handler_retries_until_connected(
    clictx: CliContext, mocker: MockerFixture
) -> None:
    clictx.mqtthost = Address("broker", 1883)
    error = mocker.patch("tcboard.cli.remotectrl.logger.error")
    warn = mocker.patch("tcboard.cli.remotectrl.logger.warning")
    working = FakeClient()
    mocker.patch(
        "tcboard.cli.remotectrl.Client",
        side_effect=[
            MqttError("Connection refused"),
            MqttError("dropped"),
            working,
        ],
    )

    async with remote_control_publisher(
        clictx, remotectrl_topic="t/%c", retry_sleep=0
    ) as task:
        assert asyncio.iscoroutine(task)
        handler = asyncio.create_task(task)
        await wait_until(lambda: any("MQTT sender" in c for c in clictx.mqttclients))
        await cancel(handler)

    error.assert_called_once()
    assert "broker not running" in error.call_args.args[0]
    assert any("reconnecting" in c.args[0] for c in warn.call_args_list)
    assert clictx.mqttclients == set()


@pytest.mark.asyncio
async def test_handler_propagates_cancellation(
    clictx: CliContext, mocker: MockerFixture
) -> None:
    clictx.mqtthost = Address("broker", 1883)
    mocker.patch("tcboard.cli.remotectrl.Client", return_value=FakeClient())

    async with remote_control_publisher(clictx, remotectrl_topic="t/%c") as task:
        assert asyncio.iscoroutine(task)
        handler = asyncio.create_task(task)
        await wait_until(lambda: any("MQTT sender" in c for c in clictx.mqttclients))

        handler.cancel()
        with pytest.raises(asyncio.CancelledError):
            await handler

    assert clictx.mqttclients == set()


# --- remotectrl plugin ------------------------------------------------------


@pytest.mark.asyncio
async def test_remotectrl_plugin_starts_from_cli(
    run_plugin: Any, clictx: CliContext, mocker: MockerFixture
) -> None:
    clictx.mqtthost = Address("broker", 1883)
    mocker.patch("tcboard.cli.remotectrl.Client", return_value=FakeClient())

    async with run_plugin(remotectrl_plugin, []) as task:
        assert asyncio.iscoroutine(task)
        close_if_coro(task)
