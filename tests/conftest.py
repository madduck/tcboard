import pytest

from tcboard.alert import Alert


@pytest.fixture
def alert() -> Alert:
    return Alert(
        text="alert text", detail="detail", matchid="matchid", deviceid="deviceid"
    )
