import pytest

from tcboard.game import Game, Result
from tcboard.livestatus import LiveStatus

from .conftest import FakeLiveData, FakeLiveDataFactoryType
from .test_livestatus import EXPECTED


def test_constructor_default_timestamp(
    FakeLiveDataFactory: FakeLiveDataFactoryType,
) -> None:
    assert FakeLiveDataFactory().timestamp is not None


def test_serialize_status_as_string(
    FakeLiveDataFactory: FakeLiveDataFactoryType,
) -> None:
    status = LiveStatus.MATCHBALL
    assert FakeLiveDataFactory(status=status).model_dump()["status"] == str(status)


@pytest.mark.parametrize("prev", LiveStatus)
@pytest.mark.parametrize("cur", LiveStatus)
def test_sequence_validity(
    FakeLiveDataFactory: FakeLiveDataFactoryType, cur: LiveStatus, prev: LiveStatus
) -> None:
    exp = EXPECTED[cur][prev]
    assert (
        FakeLiveDataFactory(status=cur).can_come_after(FakeLiveDataFactory(status=prev))
        is exp
    )


def test_str(FakeLiveDataFactory: FakeLiveDataFactoryType) -> None:
    assert (
        str(FakeLiveDataFactory(matchid="matchid", status=LiveStatus.MATCHBALL))
        == "matchid (MATCHBALL)"
    )


def test_debug_repr(FakeLiveDataFactory: FakeLiveDataFactoryType) -> None:
    assert (
        FakeLiveDataFactory(matchid="matchid", status=LiveStatus.MATCHBALL).debug_repr()
        == "matchid (MBL)"
    )


@pytest.mark.parametrize(
    "games, exp",
    [
        ([], [0, 0]),
        ([(0, 0, None)], [0, 0]),
        ([(11, 9, 0)], [1, 0]),
        ([(11, 9, 0), (11, 9, 0)], [2, 0]),
        ([(11, 9, 0), (11, 9, 0), (12, 10, 0)], [3, 0]),
        ([(11, 9, 0), (9, 11, 1), (12, 10, 0)], [2, 1]),
        ([(11, 9, 0), (9, 11, 1)], [1, 1]),
        ([(11, 9, 0), (9, 11, 1), (3, 3, None)], [1, 1]),
        ([(11, 9, 0), (9, 11, 1), (3, 3, None)], [1, 1]),
    ],
)
def test_matchscore(
    FakeLiveDataFactory: FakeLiveDataFactoryType,
    games: list[tuple[int, int, int | None]],
    exp: Result,
) -> None:
    assert (
        FakeLiveDataFactory(
            games=[Game(score=sc[:2], winner=sc[2]) for sc in games]
        ).matchscore
        == exp
    )


def test_dump_contains_modelid(FakeLiveDataFactory: FakeLiveDataFactoryType) -> None:
    ld = FakeLiveDataFactory()
    dump = ld.model_dump(round_trip=True)
    assert dump.get("_modelid") == ld.modelid


def test_dump_contains_matchid(FakeLiveDataFactory: FakeLiveDataFactoryType) -> None:
    ld = FakeLiveDataFactory(matchid="matchid")
    dump = ld.model_dump(round_trip=True)
    assert dump.get("_matchid") == "matchid"


def test_ser_val_roundtrip(FakeLiveDataFactory: FakeLiveDataFactoryType) -> None:
    ld = FakeLiveDataFactory()
    dump = ld.model_dump(round_trip=True)
    validated = FakeLiveData.make_model_instance(dump)
    assert validated == ld


def test_ser_val_roundtrip_json(FakeLiveDataFactory: FakeLiveDataFactoryType) -> None:
    ld = FakeLiveDataFactory()
    json = ld.model_dump_json(round_trip=True)
    validated = FakeLiveData.make_model_instance_json(json)
    assert validated == ld
