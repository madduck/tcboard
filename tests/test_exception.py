from tcboard.alert import Alert
from tcboard.exceptions import TCBoardException


def test_constructor_alert(alert: Alert) -> None:
    exc = TCBoardException(alert)
    assert exc.alert is alert


def test_constructor_text() -> None:
    exc = TCBoardException("text")
    assert exc.alert.text == "text"
