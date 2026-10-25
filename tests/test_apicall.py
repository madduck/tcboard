import pytest

from tcboard.apicall import APICall


def test_interpolate_path(apicall: APICall) -> None:
    assert apicall.interpolated_path == "/user/14/update"


def test_interpolate_path_missing_param(apicall: APICall) -> None:
    del apicall.params["action"]
    with pytest.raises(KeyError, match="missing path param 'action'"):
        _ = apicall.interpolated_path
