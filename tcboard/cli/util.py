from dataclasses import dataclass, field
from typing import Annotated, Never, cast

import click
from click_async_plugins import CliContext as _CliContext
from fastapi import Depends, FastAPI, HTTPException
from fastapi.requests import HTTPConnection
from starlette.status import HTTP_424_FAILED_DEPENDENCY
from tptools import Court

from tcboard.tournament import TCTournament

from ..board import TCBoard


@dataclass
class CliContext(_CliContext):
    api: FastAPI = field(default_factory=FastAPI)

    def __post_init__(self) -> None:
        self.api.state.clictx = self

    @property
    def board(self) -> TCBoard:
        return cast(TCBoard, self.itc.get("board"))

    @board.setter
    def board(self, board: TCBoard) -> None:
        self.itc.set("board", board)


pass_clictx = click.make_pass_decorator(CliContext)


def get_clictx(httpcon: HTTPConnection) -> CliContext:
    return cast(CliContext, httpcon.app.state.clictx)


def get_board(clictx: Annotated[CliContext, Depends(get_clictx)]) -> TCBoard:
    return clictx.board


def get_tournament(
    board: Annotated[TCBoard, Depends(get_board)],
) -> TCTournament | Never:
    if board.tournament is None:
        raise HTTPException(
            status_code=HTTP_424_FAILED_DEPENDENCY,
            detail="Tournament not loaded",
        )
    return board.tournament


def get_courts(
    tournament: Annotated[TCTournament, Depends(get_tournament)],
) -> list[Court]:
    return tournament.get_courts()
