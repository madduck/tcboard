import pytest

from tcboard.matchslot import MatchSlot


@pytest.mark.parametrize("slot", MatchSlot)
def test_matchslot_str(slot: MatchSlot) -> None:
    assert str(slot) == slot.name
