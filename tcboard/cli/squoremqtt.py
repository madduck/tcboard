import asyncio
import logging
from collections.abc import Mapping
from contextlib import asynccontextmanager
from functools import partial
from typing import Protocol

import click
from aiomqtt import Client, Message, MessagesIterator, MqttError
from click_async_plugins import PluginLifespan, plugin
from fastapi.datastructures import Address
from pydantic import ValidationError

from ..ext.squore import SquoreDeviceInfo, SquoreMatchLiveData
from .util import CliContext, pass_clictx

DEFAULT_MQTT_BROKER = "127.0.0.1"
DEFAULT_MQTT_PORT = 1883
SQUORE_MATCH_MQTT_TOPIC = "tptools/+/Squore/+/match"
SQUORE_DEVINFO_MQTT_TOPIC = "tptools/Squore/+/deviceInfo"

logger = logging.getLogger(__name__)
# TODO: verify logger works, the template doesn't seem applied e.g.:
#


class MessageCallback(Protocol):
    async def __call__(
        self,
        message: Message,
    ) -> None: ...


async def _receive_devinfo(message: Message, *, clictx: CliContext) -> None:
    if message.retain:
        logger.debug("Ignoring retained message")
        return

    try:
        validated = SquoreDeviceInfo.model_validate_json(message.payload)

    except ValidationError as exc:
        logger.warning(f"DeviceInfo message does not validate: {exc}")
        logger.debug(message.payload)
        return

    logger.debug(f"Received DeviceInfo on {message.topic}: {validated}")
    clictx.itc.set("squoredevinfo", validated)


async def _receive_livedata(
    message: Message, *, clictx: CliContext, ignore_retained: bool
) -> None:
    if message.retain and ignore_retained:
        logger.debug("Ignoring retained message")
        return

    try:
        validated = SquoreMatchLiveData.model_validate_json(message.payload)

    except ValidationError as exc:
        missing: list[str] = []
        for error in exc.errors():
            if error["type"] == "missing":
                missing.append(".".join(str(e) for e in error["loc"]))

            else:
                logger.warning(f"Message on {message.topic} does not validate: {error}")

        if "metadata.sourceID" in missing:
            logger.warning(
                f"Message on {message.topic} likely from a non-tptools match, "
                f"fields missing: {missing}"
            )
            logger.debug(message.payload)

        elif missing:
            logger.warning(f"Message on {message.topic} missing fields: {missing}")

        return

    logger.debug(
        f"{'Retained ' if message.retain else 'Received '}"
        f"LiveData on {message.topic}: {validated}"
    )

    clictx.itc.set("squorelivedata", validated)


async def _mqtt_loop(
    *,
    messages_gen: MessagesIterator,
    callbacks: Mapping[str, MessageCallback],
) -> None:
    async for message in messages_gen:
        if not message.payload:
            logger.warning(f"Received message without payload on topic {message.topic}")
            continue

        handled = False
        for wildcard, callback in callbacks.items():
            if message.topic.matches(wildcard):
                await callback(message)
                handled = True

        if not handled:
            logger.warning(
                f"Message on topic {message.topic} had no matching callback: "
                f"{message.payload!r}"
            )


async def _mqtt_handler(
    clictx: CliContext,
    server: str,
    port: int,
    match_topic: str,
    devinfo_topic: str,
    ignore_retained: bool,
    retry_sleep: int = 2,
) -> None:
    connstr = f"MQTT listener for {match_topic} and {devinfo_topic} on {server}:{port}"
    logger.debug(f"Starting {connstr}")
    try:
        while True:
            try:
                async with Client(server, port) as client:
                    logger.debug(f"Connected {connstr}")
                    await client.subscribe(match_topic)
                    await client.subscribe(devinfo_topic)
                    clictx.mqttclients.add(connstr)

                    callbacks = {
                        match_topic: partial(
                            _receive_livedata,
                            clictx=clictx,
                            ignore_retained=ignore_retained,
                        ),
                        devinfo_topic: partial(
                            _receive_devinfo,
                            clictx=clictx,
                        ),
                    }

                    await _mqtt_loop(
                        messages_gen=client.messages,
                        callbacks=callbacks,
                    )

            except MqttError as exc:
                if "Connection refused" in exc.args[0]:
                    logger.error(f"MQTT broker not running on {server}, port {port}")

                else:
                    logger.warning(
                        f"MQTT connection dropped {exc}, reconnecting indefinitely…"
                    )
                await asyncio.sleep(retry_sleep)

            finally:
                clictx.mqttclients.discard(connstr)

    except asyncio.CancelledError:
        logger.debug("MQTT listener exiting…")


@asynccontextmanager
async def listen_for_mqtt_messages(
    clictx: CliContext,
    *,
    server: str = DEFAULT_MQTT_BROKER,
    port: int = DEFAULT_MQTT_PORT,
    match_topic: str = SQUORE_MATCH_MQTT_TOPIC,
    devinfo_topic: str = SQUORE_DEVINFO_MQTT_TOPIC,
    ignore_retained: bool = False,
    retry_sleep: int = 2,
) -> PluginLifespan:
    clictx.mqtthost = Address(server, port)

    yield _mqtt_handler(
        clictx, server, port, match_topic, devinfo_topic, ignore_retained, retry_sleep
    )


@plugin
@click.option(
    "--server",
    "-s",
    metavar="IP",
    default=DEFAULT_MQTT_BROKER,
    show_default=True,
    help="MQTT broker to connect to",
)
@click.option(
    "--port",
    "-p",
    metavar="PORT",
    type=click.IntRange(min=1, max=65535),
    default=DEFAULT_MQTT_PORT,
    show_default=True,
    help="Port to connect to",
)
@click.option(
    "--match-topic",
    "-t",
    metavar="TOPIC",
    default=SQUORE_MATCH_MQTT_TOPIC,
    show_default=True,
    help="MQTT topic to subscribe to for match updates from Squore",
)
@click.option(
    "--devinfo-topic",
    "-d",
    metavar="TOPIC",
    default=SQUORE_DEVINFO_MQTT_TOPIC,
    show_default=True,
    help="MQTT topic to subscribe to for device updates from Squore",
)
@click.option("--ignore-retained", "-i", is_flag=True, help="Ignore retained messages")
@pass_clictx
async def squoremqtt(
    clictx: CliContext,
    server: str,
    port: int,
    match_topic: str,
    devinfo_topic: str,
    ignore_retained: bool,
) -> PluginLifespan:
    """Listen to live Squore match data on MQTT"""

    async with listen_for_mqtt_messages(
        clictx,
        server=server,
        port=port,
        match_topic=match_topic,
        devinfo_topic=devinfo_topic,
        ignore_retained=ignore_retained,
    ) as task:
        yield task
