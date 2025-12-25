import pytest

from tcboard.livestatus import LiveStatus


def test_name() -> None:
    assert str(LiveStatus.BETWEENGAMES) == "BETWEENGAMES"


def test_short() -> None:
    assert LiveStatus.BETWEENGAMES.short == "PAU"


LS = LiveStatus
EXPECTED = {cur: {prev: cur >= prev for prev in LS} for cur in LS}
# if not yet ongoing, then always true:
for cur in LS:
    EXPECTED[cur] |= {prev: True for prev in LS if prev < LS.ONGOING}
# if cur is unknown, always False:
EXPECTED[LS.ONGOING] |= dict.fromkeys(
    (LS.BETWEENGAMES, LS.FIFTEENSECONDS, LS.GAMEBALL, LS.MATCHBALL), True
)
EXPECTED[LS.FIFTEENSECONDS] |= dict.fromkeys((LS.BETWEENGAMES, LS.PREPARE), True)
EXPECTED[LS.UNKNOWN] = dict.fromkeys(LS, False)


@pytest.mark.parametrize("prev", LS)
@pytest.mark.parametrize("cur", LS)
def test_sequence_validity(cur: LiveStatus, prev: LiveStatus) -> None:
    exp = EXPECTED[cur][prev]
    assert cur.can_come_after(prev) is exp
