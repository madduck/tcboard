import logging
import pathlib
from contextlib import asynccontextmanager
from json import JSONDecodeError
from textwrap import dedent
from typing import Annotated, Any

import click
from click_async_plugins import PluginLifespan, plugin
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from httpx2 import URL
from pydantic import ValidationError
from starlette.status import HTTP_422_UNPROCESSABLE_CONTENT
from tptools.tpsrv.util import PostData, bootstrap_tournament_from_url, validate_url

from tcboard.board import TCBoard
from tcboard.tournament import TCTournament

from ..ext.squore.livedata import SquoreMatchLiveData
from .util import CliContext, get_clictx, pass_clictx

TPTOOLS_PATH_VERSION = "v1"
API_MOUNTPOINT = "/tptools"

logger = logging.getLogger(__name__)


tpapp = FastAPI()


@tpapp.post("/tournament")
async def receive_tournament(
    request: Request,
    clictx: Annotated[CliContext, Depends(get_clictx)],
) -> dict[str, Any]:
    body = await request.body()
    tournament = PostData[TCTournament].model_validate_json(body).data
    logger.info(
        f"Received {tournament.__class__.__qualname__} from tptools: {tournament}"
    )
    # clictx.board.tournament = tournament
    clictx.itc.set("tournament", tournament)
    # TODO: should we send something else? timestamp?
    return {"status": f"Received tournament: {tournament}"}


@tpapp.post("/squore/result")
async def squore_result(request: Request) -> JSONResponse:
    try:
        body = await request.body()
        result = SquoreMatchLiveData.model_validate_json(body)

    except (JSONDecodeError, ValidationError) as exc:
        raise HTTPException(
            HTTP_422_UNPROCESSABLE_CONTENT,
            "The submitted data do not appear to represent a Squore match result",
        ) from exc

    logger.info(f"Received result from tptools: {result}")
    board: TCBoard = request.app.state.clictx.board
    try:
        await board.process_squore_livedata(result)

    except Exception as exc:
        return JSONResponse(
            {
                "result": "NOK",
                "title": "An error occurred submitting the match result",
                "message": dedent(
                    f"""\
                    <html><body>
                        <h1>Please take the tablet to tournament control<h1>

                        <pre>
                        {exc}
                        </pre>

                    </body</html>
                    """
                ),
            }
        )

    else:
        return JSONResponse(
            {
                "result": "OK",
                "title": "Thank you for your diligence!",
                "message": dedent(
                    """\
                    <html><body style="background-color: #000; color: #fff">
                        <h1>Your job here is done.</h1>

                        <ul>
                        <li>Please leave the tablet at the court.</li>
                        <li>Press the (+) button at the bottom right to select
                            the next match
                        </li>
                        </ul>

                    </body></html>
                    """
                ),
            }
        )


@asynccontextmanager
async def setup_for_tptools(
    clictx: CliContext,
    api_mount_point: str = API_MOUNTPOINT,
    load_from_url: URL | None = None,
    thank_you_template: pathlib.Path | None = None,
) -> PluginLifespan:
    api_path = "/".join((api_mount_point, TPTOOLS_PATH_VERSION))

    logger.debug("Starting tptools configuration…")
    clictx.api.mount(path=api_path, app=tpapp, name="tptools")
    tpapp.state.clictx = clictx
    tpapp.state.thank_you_template = thank_you_template
    logger.info(f"Configured the app to receive tptools data at {api_path}")

    async def bootstrap_initial_tournament() -> None:
        clictx.itc.set(
            "tournament",
            None
            if load_from_url is None
            else await bootstrap_tournament_from_url(TCTournament, load_from_url),
        )

    yield bootstrap_initial_tournament()


@plugin
@click.option(
    "--api-mount-point",
    metavar="MOUNTPOINT",
    default=API_MOUNTPOINT,
    show_default=True,
    help="API mount point for tptools endpoints",
)
@click.option(
    "--load-from-url",
    "-u",
    metavar="URL",
    callback=validate_url,
    help=("On startup, try to GET tournament from this URL"),
)
@click.option(
    "-t",
    "--thank-you-template",
    metavar="TEMPLATE",
    type=click.Path(path_type=pathlib.Path),
    help="A Jinja2 template to render to confirm completion of a match",
)
@pass_clictx
async def tptools(
    clictx: CliContext,
    api_mount_point: str,
    load_from_url: URL | None,
    thank_you_template: pathlib.Path | None,
) -> PluginLifespan:
    """Mount endpoints to receive data from tptools"""

    async with setup_for_tptools(
        clictx, api_mount_point, load_from_url, thank_you_template
    ) as task:
        yield task
