import re

from pydantic import TypeAdapter, ValidationError

from ...point import AppealType, PlayerIndex, PlayerLetter, Point, ServerSide

__all__ = ["AppealType", "PlayerIndex", "PlayerLetter", "Point", "ServerSide"]

PATTERN = re.compile(
    r"(?P<AX>(?P<AS>[-RL])(?P<AP>\d+|-)|ST|[YN]L)"
    r"(?P<BX>(?P<BS>[-RL])(?P<BP>\d+|-)|ST|[YN]L)",
)

type PointDataType = AppealType | int
PointDataTypeValidator: TypeAdapter[PointDataType] = TypeAdapter(PointDataType)
PlayerIndexValidator: TypeAdapter[PlayerIndex] = TypeAdapter(PlayerIndex)
PlayerLetterValidator: TypeAdapter[PlayerLetter] = TypeAdapter(PlayerLetter)
ServerSideValidator: TypeAdapter[ServerSide] = TypeAdapter(ServerSide)


def make_point_from_squore_line(squore: str, *, duration: int | None = None) -> Point:
    m = re.fullmatch(PATTERN, squore)

    if m is None:
        raise ValueError(f"Not a Squore line I can parse: {squore}")

    d = m.groupdict()

    winner = int((a := d["AX"]) == "--")  # bool to int: True→1, False→0
    server, side = None, None
    data: PointDataType
    match a, d["BX"]:
        case ("ST", _) | (_, "ST"):
            data = "S"
        case ("YL", _) | (_, "YL"):
            data = "L"
        case ("NL", _) | (_, "NL"):
            data = "N"
        case _:
            try:
                winner = PlayerIndexValidator.validate_python(
                    # bool to int: True→1, False→0
                    int(d["AP"] == "-")
                )
                server = PlayerIndexValidator.validate_python(
                    # bool to int: True→1, False→0
                    int(d["AS"] == "-")
                )
                side = ServerSideValidator.validate_python(
                    a if (a := d["AS"]) != "-" else d["BS"]
                )
                data = PointDataTypeValidator.validate_python(
                    a if (a := d["AP"]) != "-" else d["BP"]
                )

            except ValidationError as err:
                raise ValueError(f"Not a Squore line I can parse: {squore}") from err

    return Point(
        server=server,
        serveside=side,
        data=data,
        player=1 if winner else 0,
        duration=duration,
    )
