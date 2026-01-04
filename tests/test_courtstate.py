import datetime
from typing import Literal

import pytest
from pytest_mock import MockerFixture
from tptools import Court
from tptools.namepolicy import CourtNamePolicy

from tcboard import TCMatch
from tcboard.alert import Alert
from tcboard.courtstate import CourtState
from tcboard.livedata import LiveData
from tcboard.matchstate import MatchState


def test_courtid_accessor_none() -> None:
    assert CourtState(court=None).courtid is None


def test_courtid_accessor(court: Court) -> None:
    assert CourtState(court=court).courtid == 1


def test_serialising_applies_courtnamepolicy(
    court: Court, mocker: MockerFixture
) -> None:
    pol = mocker.patch.object(CourtNamePolicy, "__call__")
    _ = CourtState(court=court).model_dump(context={"courtnamepolicy": pol})
    pol.assert_called_once_with(court)


@pytest.mark.parametrize(
    "attr, reversed",
    [("current", True), ("pending", False), ("finished", False)],
)
def test_serialising_only_current_is_reversed(
    court: Court,
    match: TCMatch,
    now: datetime.datetime,
    attr: Literal["current"] | Literal["pending"] | Literal["finished"],
    reversed: bool,
) -> None:
    matchstates = [
        MatchState[LiveData](
            match=match.model_copy(update={"id": str(n)}),
            timestamp=now + datetime.timedelta(seconds=n),
        )
        for n in range(3)
    ]
    cs = CourtState[MatchState[LiveData]](court=court)
    setattr(cs, attr, matchstates)

    dump = cs.model_dump()
    msdump = dump[attr]

    if reversed:
        matchstates.reverse()

    for d, ms in zip(msdump, matchstates, strict=True):
        assert d["match"]["id"] == ms.match.id


def test_only_alert_uuids_affect_equality(court: Court) -> None:
    cs1 = CourtState[MatchState[LiveData]](court=court)
    cs2 = CourtState[MatchState[LiveData]](court=court)
    alert1 = Alert(text="alert1")
    alert2 = alert1.model_copy(update={"text": "alert2"})

    cs1.alerts = [alert1]
    cs2.alerts = [alert2]

    assert cs1 == cs2

    cs2.alerts = [Alert(text="alert1")]  # this generates a new UUID

    assert cs1 != cs2
