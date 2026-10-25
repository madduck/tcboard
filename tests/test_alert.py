import hashlib
from datetime import datetime

import pytest
from pytest_mock import MockerFixture

from tcboard.alert import Alert, AlertClearCallback


def test_no_timestamp_means_now(alert: Alert) -> None:
    assert alert.timestamp is not None


def test_id_is_sha256_hexdigest(alert: Alert) -> None:
    assert len(alert.id) == 64
    assert all(c in "0123456789abcdef" for c in alert.id)


def test_id_matches_explicit_sha256(alert: Alert) -> None:
    exp = hashlib.sha256(
        b"\x1f".join(
            v.encode() if v is not None else b"\x00"
            for v in (
                alert.text,
                alert.detail,
                alert.matchid,
                alert.deviceid,
                alert.traceback,
            )
        )
        + b"\x1f"
    ).hexdigest()
    assert alert.id == exp


def test_id_is_content_derived(alert: Alert) -> None:
    other = Alert(
        text=alert.text,
        detail=alert.detail,
        matchid=alert.matchid,
        deviceid=alert.deviceid,
        traceback=alert.traceback,
    )
    assert alert.id == other.id


@pytest.mark.parametrize(
    "field, value",
    [
        ("text", "other"),
        ("detail", "other"),
        ("matchid", "other"),
        ("deviceid", "other"),
        ("traceback", "other"),
    ],
)
def test_id_changes_with_content(alert: Alert, field: str, value: str) -> None:
    assert alert.id != alert.model_copy(update={field: value}).id


def test_id_ignores_timestamp_and_cleared(alert: Alert) -> None:
    other = alert.model_copy(
        update={"timestamp": datetime.now(), "cleared": datetime.now()}
    )
    assert alert.id == other.id


def test_clear(alert: Alert) -> None:
    assert not alert.cleared
    alert.clear()
    assert alert.cleared


def test_clear_callback(alert: Alert, mocker: MockerFixture) -> None:
    callback = mocker.MagicMock(spec=AlertClearCallback)
    alert.set_clear_callback(callback)
    alert.clear()
    callback.assert_called_once()
    assert callback.call_args.args[0] == alert
    assert isinstance(callback.call_args.args[1], datetime)


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
