from typing import Literal

from pydantic import BaseModel

type PlayerLetter = Literal["A"] | Literal["B"]
type PlayerIndex = Literal[0] | Literal[1]
type ServerSide = Literal["L"] | Literal["R"]
type AppealType = Literal["S"] | Literal["L"] | Literal["N"]


class Point(BaseModel):
    server: PlayerIndex | None
    serveside: ServerSide | None
    player: PlayerIndex
    data: int | AppealType
    duration: int | None = None
