from collections.abc import Generator
from contextlib import contextmanager
from typing import ContextManager

import pytest

from tcboard.ext.squore.point import (
    AppealType,
    PlayerIndex,
    Point,
    ServerSide,
    make_point_from_squore_line,
)


@contextmanager
def _p(
    server: PlayerIndex | None,
    serveside: ServerSide | None,
    player: PlayerIndex,
    data: int | AppealType,
    duration: int | None = None,
) -> Generator[Point]:
    yield Point(
        server=server, serveside=serveside, player=player, data=data, duration=duration
    )


@pytest.mark.parametrize(
    "input, exp",
    [
        ("R1--", _p(0, "R", 0, 1)),
        ("L2--", _p(0, "L", 0, 2)),
        ("--R1", _p(1, "R", 1, 1)),
        ("--L2", _p(1, "L", 1, 2)),
        ("-3L-", _p(1, "L", 0, 3)),
        ("R--3", _p(0, "R", 1, 3)),
        ("R10--", _p(0, "R", 0, 10)),
        ("R--10", _p(0, "R", 1, 10)),
        ("--L10", _p(1, "L", 1, 10)),
        ("-10L-", _p(1, "L", 0, 10)),
        ("ST--", _p(None, None, 0, "S")),
        ("YL--", _p(None, None, 0, "L")),
        ("NL--", _p(None, None, 0, "N")),
        ("--ST", _p(None, None, 1, "S")),
        ("--YL", _p(None, None, 1, "L")),
        ("--NL", _p(None, None, 1, "N")),
        ("", pytest.raises(ValueError, match="Not a Squore line I can parse")),
        ("----", pytest.raises(ValueError, match="Not a Squore line I can parse")),
        ("R1-", pytest.raises(ValueError, match="Not a Squore line I can parse")),
        ("R1---", pytest.raises(ValueError, match="Not a Squore line I can parse")),
        ("-L1", pytest.raises(ValueError, match="Not a Squore line I can parse")),
        ("---L1", pytest.raises(ValueError, match="Not a Squore line I can parse")),
    ],
)
def test_squore_line_to_point(input: str, exp: ContextManager[Point]) -> None:
    with exp as ret:
        assert make_point_from_squore_line(input) == ret


def test_squore_line_to_point_with_duration() -> None:
    assert make_point_from_squore_line("R1--", duration=42).duration == 42
