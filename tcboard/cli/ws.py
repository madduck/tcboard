import logging
import pathlib
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from typing import Annotated, Any, ClassVar, Never, Self, cast

import aiostream
import click
from aiostream.core import Streamer
from click_async_plugins import PluginLifespan, plugin
from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.datastructures import URL
from fastapi.requests import HTTPConnection
from fastapi.routing import Mount
from pydantic import (
    BaseModel,
    SerializationInfo,
    SerializerFunctionWrapHandler,
    computed_field,
    field_serializer,
)
from starlette.responses import JSONResponse
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR
from tptools import Court, DeviceCourtMap
from tptools.namepolicy import (
    ClubNamePolicy,
    CountryNamePolicy,
    CourtNamePolicy,
    DrawNamePolicy,
    DrawNamePolicyParams,
    PairCombinePolicy,
    PlayerNamePolicy,
)
from tptools.tpsrv.squoresrv import (
    get_clubnamepolicy,
    get_countrynamepolicy,
    get_courtnamepolicy,
    get_paircombinepolicy,
    get_playernamepolicy,
)

from tcboard.board import TCBoard
from tcboard.courtstate import CourtState
from tcboard.exceptions import TournamentNotLoaded

from .util import (
    CliContext,
    pass_clictx,
)

WS_PATH_VERSION = "v1"
API_MOUNTPOINT = "/ws"

DEVMAP_TOML_PATH = pathlib.Path("tcboard.dev_court_map.toml")

logger = logging.getLogger(__name__)


wsapp = FastAPI()


async def listen_for_data_from_client(websocket: WebSocket) -> AsyncGenerator[str]:
    while True:
        yield await websocket.receive_text()


def interval_generator[T](
    *, interval: float | None, yld: T, skip: int | None = None
) -> aiostream.Stream[T]:
    if interval is not None:
        stream = aiostream.stream.repeat(yld, interval=interval)
    else:
        stream = aiostream.stream.just(yld)

    return stream if skip is None else stream | aiostream.pipe.skip(n=skip)


def get_remote(httpcon: HTTPConnection) -> str | None:
    return httpcon.headers.get(
        "X-Forwarded-For", httpcon.client.host if httpcon.client else "(unknown)"
    )


def get_websocket_peer(websocket: WebSocket | None) -> str | None:
    if websocket is None:
        return None

    return f"{get_remote(websocket)}:{websocket.client.port if websocket.client else 0}"


def get_devmap_path(httpcon: HTTPConnection) -> pathlib.Path | Never:
    try:
        return cast(pathlib.Path, httpcon.app.state.tcboard["devmap"])

    except (AttributeError, KeyError) as err:
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail="App state does not include tcboard.devmap",
        ) from err


def get_dev_map(
    path: Annotated[pathlib.Path, Depends(get_devmap_path)],
) -> DeviceCourtMap:
    try:
        with open(path, "rb") as f:
            return DeviceCourtMap(f)

    except FileNotFoundError:
        logger.warning(f"Squore device to court map not found at {path}, ignoring…")

    return DeviceCourtMap()


def get_drawnamepolicy(
    policyparams: Annotated[DrawNamePolicyParams, Query()],
) -> DrawNamePolicy:
    return DrawNamePolicy(**DrawNamePolicyParams.extract_subset(policyparams))


class DisplayData(BaseModel):
    rev: int = 0
    courtstates: list[CourtState] = []

    @field_serializer("courtstates", mode="wrap")
    def _courtstates_serializer(
        self,
        courtstates: list[CourtState],
        _: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> list[CourtState]:
        ctx = info.context or {}
        courtids = ctx.get("courtids")

        if courtids is None:
            return courtstates
        else:
            return [cs for cs in courtstates if cs.court and cs.court.id in courtids]


class CourtData(BaseModel):
    court: Court
    label: str

    @computed_field
    def id(self) -> int:
        return self.court.id


@dataclass
class WSHandler:
    courtids: list[int] | None = None
    timeout: float | None = None
    at_most_every: float | None = None

    Timeout: ClassVar[object] = object()
    NoBoard: ClassVar[object] = object()

    def __post_init__(self) -> None:
        self._events_gen: Streamer[Any] | None = None
        self._websocket: WebSocket | None = None

    @property
    def url(self) -> URL | None:
        return self._websocket.url if self._websocket is not None else None

    @property
    def peer(self) -> str | None:
        return get_websocket_peer(self._websocket)

    @property
    def connstr(self) -> str:
        return (
            f"WebSocket connection from {get_websocket_peer(self._websocket)} "
            f"to {self.url} (courts={self.courtids}, timeout={self.timeout}, "
            f"at_most_every={self.at_most_every})"
        )

    async def disconnect(self, reason: str | None = None) -> None:
        if self._websocket is None:
            return

        await self._websocket.close(reason=reason)
        self._websocket = None

    @contextmanager
    def _track_and_log_connection(self, websocket: WebSocket) -> Generator[None]:
        clictx = websocket.app.state.clictx
        self._websocket = websocket
        clictx.websockets.append(self)
        peer = self.peer
        logger.info(
            f"Client {self.peer} connected and subscribed to "
            f"{
                'all courts'
                if self.courtids is None
                else ('court ' + ','.join(str(c) for c in self.courtids))
            }"
        )
        try:
            yield None

        finally:
            logger.info(f"Client {peer} disconnected")
            clictx.websockets.remove(self)
            self._websocket = None

    @asynccontextmanager
    async def accept(self, websocket: WebSocket) -> AsyncGenerator[Self]:
        await websocket.accept()

        with self._track_and_log_connection(websocket):
            # try:
            clictx = websocket.app.state.clictx
            event_sources = aiostream.stream.merge(
                clictx.itc.updates(
                    "board",
                    at_most_every=self.at_most_every,
                    yield_for_no_value=self.NoBoard,
                ),
                listen_for_data_from_client(websocket),
                # skip=1 because ITC.updates generates the first event right await
                interval_generator(interval=self.timeout, yld=self.Timeout, skip=1),
            )

            try:
                async with event_sources.stream() as events_gen:
                    self._events_gen = events_gen
                    yield self

            finally:
                self._events_gen = None

    async def events(self) -> AsyncGenerator[Any]:
        while True:
            if self._events_gen:
                yield await anext(self._events_gen)
            else:
                break

    async def send_data(
        self,
        data: BaseModel,
        *,
        courtnamepolicy: CourtNamePolicy | None = None,
        drawnamepolicy: DrawNamePolicy | None = None,
        clubnamepolicy: ClubNamePolicy | None = None,
        countrynamepolicy: CountryNamePolicy | None = None,
        playernamepolicy: PlayerNamePolicy | None = None,
        paircombinepolicy: PairCombinePolicy | None = None,
    ) -> None | Never:
        if self._websocket is None:
            raise RuntimeError("Trying to send board on non-existent web socket")

        logger.debug(f"Sending JSON data to {self.peer}")
        await self._websocket.send_text(
            data.model_dump_json(
                context={
                    "courtids": self.courtids,
                    "courtnamepolicy": courtnamepolicy,
                    "drawnamepolicy": drawnamepolicy,
                    "clubnamepolicy": clubnamepolicy,
                    "countrynamepolicy": countrynamepolicy,
                    "playernamepolicy": playernamepolicy,
                    "paircombinepolicy": paircombinepolicy,
                }
            )
        )
        return None

    @classmethod
    def make_instance(
        cls,
        # dev_map: Annotated[DeviceCourtMap, Depends(get_dev_map)],
        # clientip: Annotated[str | None, Depends(get_remote)],
        # courts: Annotated[list[Court], Depends(get_courts)],
        court: Annotated[list[int] | None, Query()] = None,
        timeout: float | None = None,
        at_most_every: float | None = None,
    ) -> Self:
        # if not court and clientip is not None:
        #     if (c := dev_map.find_court_for_ip(clientip, courts=courts)) is not None:
        #         court = [c.id]

        return cls(
            courtids=court,
            timeout=timeout,
            at_most_every=at_most_every,
        )

    async def send_welcome(
        self,
        # courts: list[Court],
        courtnamepolicy: CourtNamePolicy | None = None,
    ) -> None | Never:
        if self._websocket is None:
            raise RuntimeError("Trying to send board on non-existent web socket")

        api = cast(FastAPI, self._websocket.app.state.clictx.api)
        apiroute = cast(
            Mount, [r for r in api.routes if getattr(r, "name", None) == "apiapp"][0]
        )
        baseurl = self._websocket.base_url
        baseurl = baseurl.replace(
            scheme="http" if baseurl.scheme == "ws" else "https",
            path=apiroute.path,
        )

        courtnamepolicy = courtnamepolicy or CourtNamePolicy()

        logger.debug(f"Sending welcome packet to {self.peer}")
        await self._websocket.send_json(
            {
                "schema": DisplayData.model_json_schema(mode="serialization"),
                "apiurl": str(baseurl.replace(path=apiroute.path)),
                # "courtdata": [
                #     CourtData(court=c, label=courtnamepolicy(c)).model_dump(
                #         context={"courtnamepolicy": courtnamepolicy}
                #     )
                #     for c in courts
                # ],
            }
        )
        return None


@wsapp.get("/schema")
async def get_schema() -> JSONResponse:
    return JSONResponse(
        DisplayData.model_json_schema(mode="serialization"),
        headers={
            # "Content-Disposition": "attachment; "
            # f'filename="board-schema-{WS_PATH_VERSION}.json"'
        },
    )


def process_tcboard_event(
    board: TCBoard, curdata: DisplayData | None
) -> DisplayData | None:
    newdata = DisplayData(
        rev=board.rev,
        courtstates=list(board.get_courtstates_by_court().values()),
    )
    if curdata != newdata:
        return newdata.model_copy(deep=True)
    else:
        return None


@wsapp.websocket("/")
async def websocket(
    websocket: WebSocket,
    wshandler: Annotated[WSHandler, Depends(WSHandler.make_instance)],
    drawnamepolicy: Annotated[DrawNamePolicy, Depends(get_drawnamepolicy)],
    courtnamepolicy: Annotated[CourtNamePolicy, Depends(get_courtnamepolicy)],
    playernamepolicy: Annotated[PlayerNamePolicy, Depends(get_playernamepolicy)],
    paircombinepolicy: Annotated[PairCombinePolicy, Depends(get_paircombinepolicy)],
    countrynamepolicy: Annotated[CountryNamePolicy, Depends(get_countrynamepolicy)],
    clubnamepolicy: Annotated[ClubNamePolicy, Depends(get_clubnamepolicy)],
) -> None:
    async with wshandler.accept(websocket):
        await wshandler.send_welcome(
            courtnamepolicy=courtnamepolicy,
        )

        try:
            data = None
            async for event in wshandler.events():
                match event:
                    case TCBoard():
                        try:
                            if (
                                newdata := process_tcboard_event(event, data)
                            ) is not None:
                                data = newdata
                            else:
                                logger.debug(
                                    f"Board data unchanged for {wshandler.peer}, "
                                    "skipping…"
                                )
                                # TODO: all updates seem to register unchanged
                                continue

                        except TournamentNotLoaded:
                            logger.warning("No tournament loaded yet.")
                            continue

                    case ev if ev is WSHandler.NoBoard:
                        logger.warning("No board loaded yet.")
                        continue

                    case ev if ev is WSHandler.Timeout:
                        logger.debug(
                            f"Timeout reached for {wshandler.peer}, (re)sending board…"
                        )

                    case str():
                        logger.debug(f"Client {wshandler.peer} sent: {event}")
                        continue

                    case _:
                        logger.warning(
                            f"Unexpected event for client {wshandler.peer}: {event}"
                        )
                        continue

                if data is None:
                    logger.warning("Board is None")
                    continue

                await wshandler.send_data(
                    data,
                    courtnamepolicy=courtnamepolicy,
                    drawnamepolicy=drawnamepolicy,
                    clubnamepolicy=clubnamepolicy,
                    countrynamepolicy=countrynamepolicy,
                    playernamepolicy=playernamepolicy,
                    paircombinepolicy=paircombinepolicy,
                )

        except WebSocketDisconnect:
            logger.debug("WebSocket disconnected remotely")


@asynccontextmanager
async def configure_for_websockets(
    clictx: CliContext,
    devmap_toml: pathlib.Path = DEVMAP_TOML_PATH,
    api_mount_point: str = API_MOUNTPOINT,
) -> PluginLifespan:
    api_path = "/".join((api_mount_point, WS_PATH_VERSION))

    logger.debug("Starting websocket manager…")
    clictx.api.mount(path=api_path, app=wsapp, name="wsapp")
    wsapp.state.clictx = clictx
    wsapp.state.tcboard = {"devmap": devmap_toml}
    logger.info(f"Configured the app to handle websockets from {api_path}")

    yield None


@plugin
@click.option(
    "--devmap-toml",
    metavar="PATH",
    type=click.Path(path_type=pathlib.Path),
    default=DEVMAP_TOML_PATH,
    show_default=True,
    help="Path of file to use for device to court mapping",
)
@click.option(
    "--api-mount-point",
    metavar="MOUNTPOINT",
    default=API_MOUNTPOINT,
    show_default=True,
    help="API mount point for Squore endpoints",
)
@pass_clictx
async def ws(
    clictx: CliContext,
    devmap_toml: pathlib.Path,
    api_mount_point: str,
) -> PluginLifespan:
    """Mount endpoints to serve board data on WebSockets"""

    async with configure_for_websockets(clictx, devmap_toml, api_mount_point) as task:
        yield task
