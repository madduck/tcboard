from datetime import datetime

from pydantic import BaseModel, field_serializer
from tptools.util import ScoreType

from .point import Point

# type Result = tuple[int, int]
type Result = list[int]


class Game(BaseModel):
    score: ScoreType
    starttime: datetime | None = None
    endtime: datetime | None = None
    winner: int | None = None
    # Winner seems a redundant field, but it is not. A game could be live, i.e. ongoing,
    # and then None means there is no winner. We could of course compute this too, but
    # then we'd need to know the match format here. Let's keep it simple for now.
    scoreline: list[Point] = []

    @field_serializer("score", mode="plain")
    def _score_as_list(self, value: ScoreType) -> Result:
        # Convert the tuple to a list because otherwise json2ts generates:
        #
        # /**
        #  * @minItems 2
        #  * @maxItems 2
        #  */
        # export type Result = [unknown, unknown];
        #
        # and thus loses the typing.
        return list(value)
