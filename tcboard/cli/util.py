# needed < 3.14 so that annotations aren't evaluated
from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

import click
from click_async_plugins import CliContext as _CliContext
from fastapi import FastAPI
from fastapi.requests import HTTPConnection


@dataclass
class CliContext(_CliContext):
    api: FastAPI = field(default_factory=FastAPI)

    def __post_init__(self) -> None:
        self.api.state.clictx = self


pass_clictx = click.make_pass_decorator(CliContext)


def get_clictx(httpcon: HTTPConnection) -> CliContext:  # pragma: nocover
    return cast(CliContext, httpcon.app.state.clictx)
