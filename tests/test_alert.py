from datetime import datetime

import pytest

from tcboard.alert import Alert


def test_no_timestamp_means_now(alert: Alert) -> None:
    assert alert.timestamp is not None


def test_clear(alert: Alert) -> None:
    assert not alert.cleared
    alert.clear()
    assert alert.cleared


TESTS = [
    ("alert text", "detail", "matchid", None, True),
    ("alert text", "DETAIL IGNORED", "matchid", None, True),
    ("DIFF", "detail", "matchid", None, False),
    ("alert text", "detail", "DIFF", None, False),
    ("alert text", "detail", "other", datetime.now(), False),
]


@pytest.mark.parametrize("text, detail, matchid, cleared, eq", TESTS)
def test_equality(
    alert: Alert,
    text: str,
    detail: str,
    matchid: str,
    cleared: datetime | None,
    eq: bool,
) -> None:
    assert eq is (
        alert == Alert(text=text, detail=detail, matchid=matchid, cleared=cleared)
    )


@pytest.mark.parametrize("text, detail, matchid, cleared, eq", TESTS)
def test_hash(
    alert: Alert,
    text: str,
    detail: str,
    matchid: str,
    cleared: datetime | None,
    eq: bool,
) -> None:
    other = Alert(text=text, detail=detail, matchid=matchid, cleared=cleared)
    assert eq is (hash(alert) == hash(other))


def test_equality_incompatible(alert: Alert) -> None:
    assert alert != object()


def test_from_exception() -> None:
    try:
        raise Exception("text")

    except Exception as exc:
        alert = Alert.from_exception(exc)
        assert alert.text == "text"
        assert alert.traceback is not None


def test_from_exception_no_traceback() -> None:
    assert Alert.from_exception(Exception()).traceback is None


@pytest.mark.parametrize(
    "text, detail, matchid, deviceid, exp",
    [
        ("text", None, None, None, "text"),
        ("text", "detail", None, None, "text: detail"),
        ("text", "detail", "matchid", None, "text: detail, matchid=matchid"),
        ("text", None, "matchid", None, "text, matchid=matchid"),
        (
            "text",
            None,
            "matchid",
            "deviceid",
            "text, matchid=matchid, deviceid=deviceid",
        ),
        ("text", None, None, "deviceid", "text, deviceid=deviceid"),
        ("text", "detail", "matchid", None, "text: detail, matchid=matchid"),
        (
            "text",
            "detail",
            "matchid",
            "deviceid",
            "text: detail, matchid=matchid, deviceid=deviceid",
        ),
        ("text", "detail", None, "deviceid", "text: detail, deviceid=deviceid"),
    ],
)
def test_str(
    text: str,
    detail: str | None,
    matchid: str | None,
    deviceid: str | None,
    exp: str,
) -> None:
    assert (
        str(Alert(text=text, detail=detail, matchid=matchid, deviceid=deviceid)) == exp
    )
