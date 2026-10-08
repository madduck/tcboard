import logging
from contextlib import asynccontextmanager
from typing import Annotated

import click
from click_async_plugins import PluginLifespan, plugin
from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Path,
    Response,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import UUID4
from starlette.status import HTTP_204_NO_CONTENT, HTTP_404_NOT_FOUND
from tptools import Court

from tcboard.cli.util import get_remote

from ..exceptions import EntityNotFoundError
from .util import CliContext, get_clictx, get_courts, pass_clictx

API_PATH_VERSION = "v1"
API_MOUNTPOINT = "/api"

logger = logging.getLogger(__name__)


apiapp = FastAPI()

apiapp.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "*"
        # "http://localhost:5173",
        # "http://tcdisp:5173",
        # "http://tcdisp",
        # "http://albatross.siby:5173",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["X-Requested-With", "Content-Type"],
)


@apiapp.get("/")
async def root() -> Response:
    return Response(status_code=HTTP_204_NO_CONTENT)


@apiapp.get("/courts")
async def courts(
    courts: Annotated[list[Court], Depends(get_courts)],
    remote: Annotated[str, Depends(get_remote)],
) -> list[Court]:
    logger.info(f"Courts request from {remote}, returning {len(courts)} records")
    return courts


@apiapp.patch("/match/ack/{matchid}")
async def match_ack(
    matchid: Annotated[str, Path(title="The ID of the match to ack")],
    clictx: Annotated[CliContext, Depends(get_clictx)],
) -> Response:
    try:
        logger.info(f"Acking match {matchid}")
        await clictx.board.ack_match(matchid)

    except EntityNotFoundError as exc:
        raise HTTPException(HTTP_404_NOT_FOUND, f"No match with ID {matchid}") from exc

    else:
        return Response(status_code=HTTP_204_NO_CONTENT)


@apiapp.patch("/match/unack/{matchid}")
async def match_unack(
    matchid: Annotated[str, Path(title="The ID of the match to unack")],
    clictx: Annotated[CliContext, Depends(get_clictx)],
) -> Response:
    try:
        logger.info(f"Unacking match {matchid}")
        await clictx.board.ack_match(matchid, acked=False)

    except EntityNotFoundError as exc:
        raise HTTPException(HTTP_404_NOT_FOUND, f"No match with ID {matchid}") from exc

    else:
        return Response(status_code=HTTP_204_NO_CONTENT)


@apiapp.patch("/match/reset/{matchid}")
async def match_reset(
    matchid: Annotated[str, Path(title="The ID of the match to ack")],
    clictx: Annotated[CliContext, Depends(get_clictx)],
) -> Response:
    try:
        logger.info(f"Resetting match {matchid}")
        await clictx.board.reset_match(matchid)

    except EntityNotFoundError as exc:
        raise HTTPException(HTTP_404_NOT_FOUND, f"No match with ID {matchid}") from exc

    else:
        return Response(status_code=HTTP_204_NO_CONTENT)


@apiapp.patch("/alert/clear/{courtid}/{alertid}")
async def alert_clear(
    courtid: Annotated[int, Path(title="The ID of the court of the alert to clear")],
    alertid: Annotated[UUID4, Path(title="The ID of the alert to clear")],
    clictx: Annotated[CliContext, Depends(get_clictx)],
) -> Response:
    try:
        logger.info(f"Clearing alert on court with ID {courtid}: {alertid}")
        await clictx.board.clear_alert(courtid, alertid)

    except EntityNotFoundError as exc:
        raise HTTPException(
            HTTP_404_NOT_FOUND, f"No alert with ID {alertid} on court with ID {courtid}"
        ) from exc

    else:
        return Response(status_code=HTTP_204_NO_CONTENT)


@asynccontextmanager
async def configure_api(
    clictx: CliContext,
    api_mount_point: str = API_MOUNTPOINT,
) -> PluginLifespan:
    api_path = "/".join((api_mount_point, API_PATH_VERSION))

    logger.debug("Starting API configureation…")
    clictx.api.mount(path=api_path, app=apiapp, name="apiapp")
    apiapp.state.clictx = clictx
    logger.info(f"Configured the API at {api_path}")

    yield None


@plugin
@click.option(
    "--api-mount-point",
    metavar="MOUNTPOINT",
    default=API_MOUNTPOINT,
    show_default=True,
    help="API mount point for Squore endpoints",
)
@pass_clictx
async def api(
    clictx: CliContext,
    api_mount_point: str,
) -> PluginLifespan:
    """Mount API endpoints for data manipulation"""

    async with configure_api(clictx, api_mount_point) as task:
        yield task
