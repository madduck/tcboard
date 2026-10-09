import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Protocol, Self

import aiostream
import click
from aiomqtt import Client, MqttError
from click_async_plugins import PluginLifespan, depends_on, plugin
from tptools import Court, Match

from tcboard.ext.squore.livedata import SquoreMatchLiveData

from .. import TCTournament
from ..ext.squore import SquoreMatch
from .util import CliContext, pass_clictx

SQUORE_REMOTE_CONTROL_TOPIC = "double-yellow/Squore/%c/remoteControl"

logger = logging.getLogger(__name__)
# TODO: verify logger works, the template doesn't seem applied e.g.:
#


class SquoreMatchWithCourt(SquoreMatch):
    court: int | None

    @classmethod
    def from_match(cls, match: Match) -> Self:
        base = SquoreMatch.from_match(match)
        return cls(
            court=None if match.court is None else match.court.id, **base.model_dump()
        )


class RemoteCtrlCallbackType(Protocol):
    async def __call__(self, match: Match, deviceid: str) -> None: ...


class RemoteControlManager:
    def __init__(self) -> None:
        self._matches_on_courts: dict[Court, Match | None] = {}
        self._courts_to_device_map: dict[int, str] = {}

    async def receive_tournament(
        self, tournament: TCTournament, callback: RemoteCtrlCallbackType
    ) -> None:
        for court in tournament.courts.values():
            if (cm := court.current_match) is not None:
                if cm != self._matches_on_courts.get(court):
                    if (device := self._courts_to_device_map.get(court.id)) is not None:
                        logger.info(
                            f"Match {cm.id} being put on court {court}, "
                            f"sending remote control to {device}"
                        )
                        await callback(cm, device)
                    else:
                        logger.warning(
                            f"Match {cm.id} being put on court {court}, "
                            "but we don't know the device ID (yet)"
                        )

            elif self._matches_on_courts.get(court) is not None:
                logger.info(f"Court {court} cleared")

            self._matches_on_courts[court] = court.current_match

    async def receive_livedata(self, livedata: SquoreMatchLiveData) -> None:
        if livedata.court is not None:
            self._courts_to_device_map[livedata.court] = livedata.deviceid


async def remote_control_loop(
    clictx: CliContext, client: Client, remote_control_topic: str
) -> None:
    async def _send_remote_control_packet(match: Match, deviceid: str) -> None:
        sm = SquoreMatchWithCourt.from_match(match)
        await client.publish(
            remote_control_topic.replace("%c", deviceid), sm.model_dump_json()
        )

    mgr = RemoteControlManager()

    streams = (
        clictx.itc.updates("tournament", yield_immediately=True),
        clictx.itc.updates("squorelivedata", yield_immediately=True),
    )

    async with aiostream.stream.merge(*streams).stream() as events_gen:
        async for event in events_gen:
            if event is None:
                continue
            elif isinstance(event, TCTournament):
                await mgr.receive_tournament(event, _send_remote_control_packet)
            elif isinstance(event, SquoreMatchLiveData):
                await mgr.receive_livedata(event)
            else:
                logger.warning(
                    "Received unexpected event "
                    f"of type {event.__class__.__qualname__}: {event}"
                )


@asynccontextmanager
async def remote_control_publisher(
    clictx: CliContext,
    *,
    remotectrl_topic: str = SQUORE_REMOTE_CONTROL_TOPIC,
    retry_sleep: int = 2,
) -> PluginLifespan:
    if clictx.mqtthost is not None:
        server, port = clictx.mqtthost.host, clictx.mqtthost.port
    else:
        raise ValueError("CliContext.mqtthost is unset")

    connstr = f"MQTT sender on {remotectrl_topic} to {server}:{port}"
    logger.debug(f"Starting {connstr}")

    try:
        while True:
            try:
                async with Client(server, port) as client:
                    logger.debug(f"Connected {connstr}")
                    clictx.mqttclients.add(connstr)

                    yield remote_control_loop(clictx, client, remotectrl_topic)

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
        logger.debug("MQTT client exiting…")


@plugin
@depends_on("squoremqtt")
@click.option(
    "--remotectrl-topic",
    "-t",
    metavar="TOPIC",
    default=SQUORE_REMOTE_CONTROL_TOPIC,
    show_default=True,
    help="MQTT topic to publish remote control messages to",
)
@pass_clictx
async def remotectrl(
    clictx: CliContext,
    remotectrl_topic: str,
) -> PluginLifespan:
    """Remote-control clients when matches are put on court"""

    async with remote_control_publisher(
        clictx, remotectrl_topic=remotectrl_topic
    ) as task:
        yield task
