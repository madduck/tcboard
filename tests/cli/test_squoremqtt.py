import asyncio
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock

import pytest
from aiomqtt import Message, MqttError
from fastapi.datastructures import Address
from pytest_mock import MockerFixture

from tcboard.cli.squoremqtt import (
    SQUORE_DEVINFO_MQTT_TOPIC,
    SQUORE_MATCH_MQTT_TOPIC,
    _mqtt_handler,
    _mqtt_loop,
    _receive_devinfo,
    _receive_livedata,
    listen_for_mqtt_messages,
)
from tcboard.cli.squoremqtt import (
    squoremqtt as squoremqtt_plugin,
)
from tcboard.cli.util import CliContext

from .conftest import cancel, close_if_coro, wait_until

DEVINFO_PAYLOAD = (
    b'{"device": "squore!", "batteryCharging": true, "batteryPercentage": 42}'
)


def make_message(topic: str, payload: bytes | None, retain: bool = False) -> Message:
    return Message(
        topic=topic,
        payload=payload or b"",
        qos=0,
        retain=retain,
        mid=1,
        properties=None,
    )


class FakeClient:
    """Minimal stand-in for aiomqtt.Client used as an async context manager."""

    def __init__(self, messages: AsyncGenerator[Message]) -> None:
        self.messages = messages
        self.subscribe = AsyncMock()

    async def __aenter__(self) -> "FakeClient":
        return self

    async def __aexit__(self, *_: Any) -> bool:
        return False


async def _forever_after(*msgs: Message) -> AsyncGenerator[Message]:
    for m in msgs:
        yield m
    await asyncio.Event().wait()


# --- _receive_devinfo -------------------------------------------------------


@pytest.mark.asyncio
async def test_receive_devinfo_ignores_retained(clictx: CliContext) -> None:
    msg = make_message("tptools/Squore/abc/deviceInfo", DEVINFO_PAYLOAD, retain=True)
    await _receive_devinfo(msg, clictx=clictx)
    assert clictx.itc.get("squoredevinfo") is None


@pytest.mark.asyncio
async def test_receive_devinfo_warns_on_invalid_payload(
    clictx: CliContext, mocker: MockerFixture
) -> None:
    warn = mocker.patch("tcboard.cli.squoremqtt.logger.warning")
    msg = make_message("tptools/Squore/abc/deviceInfo", b"{}")
    await _receive_devinfo(msg, clictx=clictx)
    assert clictx.itc.get("squoredevinfo") is None
    warn.assert_called_once()
    assert "does not validate" in warn.call_args.args[0]


@pytest.mark.asyncio
async def test_receive_devinfo_stores_valid_devinfo(clictx: CliContext) -> None:
    msg = make_message("tptools/Squore/abc/deviceInfo", DEVINFO_PAYLOAD)
    await _receive_devinfo(msg, clictx=clictx)
    devinfo = clictx.itc.get("squoredevinfo")
    assert devinfo is not None
    assert devinfo.deviceid == "squore!"


# --- _receive_livedata ------------------------------------------------------


@pytest.mark.asyncio
async def test_receive_livedata_ignores_retained_when_asked(
    clictx: CliContext,
) -> None:
    msg = make_message("tptools/x/Squore/1/match", b"{}", retain=True)
    await _receive_livedata(msg, clictx=clictx, ignore_retained=True)
    assert clictx.itc.get("squorelivedata") is None


@pytest.mark.asyncio
async def test_receive_livedata_accepts_retained_when_not_ignored(
    clictx: CliContext, mocker: MockerFixture
) -> None:
    live = mocker.patch("tcboard.cli.squoremqtt.SquoreMatchLiveData")
    live.model_validate_json.return_value = "livedata"
    msg = make_message("tptools/x/Squore/1/match", b"{}", retain=True)
    await _receive_livedata(msg, clictx=clictx, ignore_retained=False)
    assert clictx.itc.get("squorelivedata") == "livedata"


@pytest.mark.asyncio
async def test_receive_livedata_stores_valid_livedata(
    clictx: CliContext, mocker: MockerFixture
) -> None:
    live = mocker.patch("tcboard.cli.squoremqtt.SquoreMatchLiveData")
    live.model_validate_json.return_value = "livedata"
    msg = make_message("tptools/x/Squore/1/match", b"{}")
    await _receive_livedata(msg, clictx=clictx, ignore_retained=False)
    assert clictx.itc.get("squorelivedata") == "livedata"


@pytest.mark.asyncio
async def test_receive_livedata_non_tptools_source_is_logged(
    clictx: CliContext, mocker: MockerFixture
) -> None:
    warn = mocker.patch("tcboard.cli.squoremqtt.logger.warning")
    debug = mocker.patch("tcboard.cli.squoremqtt.logger.debug")
    msg = make_message("tptools/x/Squore/1/match", b'{"metadata": {}}')
    await _receive_livedata(msg, clictx=clictx, ignore_retained=False)
    assert clictx.itc.get("squorelivedata") is None
    assert any("non-tptools" in c.args[0] for c in warn.call_args_list)
    debug.assert_any_call(b'{"metadata": {}}')


@pytest.mark.asyncio
async def test_receive_livedata_reports_missing_fields(
    clictx: CliContext, mocker: MockerFixture
) -> None:
    warn = mocker.patch("tcboard.cli.squoremqtt.logger.warning")
    msg = make_message("tptools/x/Squore/1/match", b"{}")
    await _receive_livedata(msg, clictx=clictx, ignore_retained=False)
    assert clictx.itc.get("squorelivedata") is None
    assert any("missing fields" in c.args[0] for c in warn.call_args_list)


@pytest.mark.asyncio
async def test_receive_livedata_reports_non_missing_errors(
    clictx: CliContext, mocker: MockerFixture
) -> None:
    warn = mocker.patch("tcboard.cli.squoremqtt.logger.warning")
    msg = make_message("tptools/x/Squore/1/match", b'{"court": "not-a-number"}')
    await _receive_livedata(msg, clictx=clictx, ignore_retained=False)
    assert clictx.itc.get("squorelivedata") is None
    assert any("does not validate" in c.args[0] for c in warn.call_args_list)


# --- _mqtt_loop -------------------------------------------------------------


@pytest.mark.asyncio
async def test_mqtt_loop_dispatches_and_warns(mocker: MockerFixture) -> None:
    warn = mocker.patch("tcboard.cli.squoremqtt.logger.warning")
    cb = AsyncMock()

    async def messages() -> AsyncGenerator[Message]:
        yield make_message("tptools/Squore/x/deviceInfo", None)  # no payload
        yield make_message("tptools/Squore/x/deviceInfo", b"{}")  # callback
        yield make_message("unrelated/topic", b"{}")  # no callback

    await _mqtt_loop(
        messages_gen=messages(),
        callbacks={SQUORE_DEVINFO_MQTT_TOPIC: cb},
    )

    cb.assert_awaited_once()
    texts = [c.args[0] for c in warn.call_args_list]
    assert any("without payload" in t for t in texts)
    assert any("had no matching callback" in t for t in texts)


# --- _mqtt_handler ----------------------------------------------------------


@pytest.mark.asyncio
async def test_mqtt_handler_retries_then_dispatches(
    clictx: CliContext, mocker: MockerFixture
) -> None:
    error = mocker.patch("tcboard.cli.squoremqtt.logger.error")
    warn = mocker.patch("tcboard.cli.squoremqtt.logger.warning")

    working = FakeClient(
        _forever_after(make_message("tptools/Squore/abc/deviceInfo", DEVINFO_PAYLOAD))
    )
    client_cls = mocker.patch(
        "tcboard.cli.squoremqtt.Client",
        side_effect=[
            MqttError("Connection refused"),
            MqttError("network is unreachable"),
            working,
        ],
    )

    task = asyncio.create_task(
        _mqtt_handler(
            clictx,
            "broker",
            1883,
            SQUORE_MATCH_MQTT_TOPIC,
            SQUORE_DEVINFO_MQTT_TOPIC,
            ignore_retained=False,
            retry_sleep=0,
        )
    )
    await wait_until(lambda: clictx.itc.get("squoredevinfo") is not None)
    assert any("MQTT listener" in c for c in clictx.mqttclients)
    await cancel(task)

    assert client_cls.call_count == 3
    working.subscribe.assert_any_await(SQUORE_MATCH_MQTT_TOPIC)
    working.subscribe.assert_any_await(SQUORE_DEVINFO_MQTT_TOPIC)
    error.assert_called_once()
    assert "broker not running" in error.call_args.args[0]
    assert any("reconnecting" in c.args[0] for c in warn.call_args_list)
    assert clictx.mqttclients == set()


@pytest.mark.asyncio
async def test_mqtt_handler_livedata_callback_respects_ignore_retained(
    clictx: CliContext, mocker: MockerFixture
) -> None:
    live = mocker.patch("tcboard.cli.squoremqtt.SquoreMatchLiveData")
    live.model_validate_json.return_value = "livedata"
    retained = make_message("tptools/x/Squore/1/match", b"{}", retain=True)
    fresh = make_message("tptools/x/Squore/2/match", b"{}", retain=False)

    client = FakeClient(_forever_after(retained, fresh))
    mocker.patch("tcboard.cli.squoremqtt.Client", return_value=client)

    task = asyncio.create_task(
        _mqtt_handler(
            clictx,
            "broker",
            1883,
            SQUORE_MATCH_MQTT_TOPIC,
            SQUORE_DEVINFO_MQTT_TOPIC,
            ignore_retained=True,
        )
    )
    await wait_until(lambda: clictx.itc.get("squorelivedata") is not None)
    await cancel(task)
    assert clictx.itc.get("squorelivedata") == "livedata"


@pytest.mark.asyncio
async def test_mqtt_handler_no_mqtt_error_non_refused(
    clictx: CliContext, mocker: MockerFixture
) -> None:
    client = FakeClient(_forever_after())
    mocker.patch(
        "tcboard.cli.squoremqtt.Client",
        side_effect=[MqttError("other"), client],
    )
    task = asyncio.create_task(
        _mqtt_handler(
            clictx,
            "broker",
            1883,
            SQUORE_MATCH_MQTT_TOPIC,
            SQUORE_DEVINFO_MQTT_TOPIC,
            ignore_retained=False,
            retry_sleep=0,
        )
    )
    await wait_until(lambda: any("MQTT listener" in c for c in clictx.mqttclients))
    await cancel(task)


# --- listen_for_mqtt_messages and plugin -----------------------------------


@pytest.mark.asyncio
async def test_listen_for_mqtt_messages_sets_host_and_yields_handler(
    clictx: CliContext,
) -> None:
    async with listen_for_mqtt_messages(clictx, server="10.0.0.5", port=1884) as task:
        assert asyncio.iscoroutine(task)
        close_if_coro(task)

    assert clictx.mqtthost == Address("10.0.0.5", 1884)


@pytest.mark.asyncio
async def test_squoremqtt_plugin(run_plugin: Any, clictx: CliContext) -> None:
    async with run_plugin(
        squoremqtt_plugin,
        ["--server", "broker.local", "--port", "1999", "--ignore-retained"],
    ) as task:
        close_if_coro(task)
    assert clictx.mqtthost == Address("broker.local", 1999)
