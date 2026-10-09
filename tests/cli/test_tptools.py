import pathlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from httpx2 import URL
from pytest_mock import MockerFixture
from tptools.tpsrv.util import PostData

from tcboard import TCTournament
from tcboard.cli.tptools import (
    API_MOUNTPOINT,
    TPTOOLS_PATH_VERSION,
    setup_for_tptools,
    tpapp,
)
from tcboard.cli.tptools import (
    tptools as tptools_plugin,
)
from tcboard.cli.util import CliContext


@pytest.fixture
def tpclient(clictx: CliContext) -> TestClient:
    tpapp.state.clictx = clictx
    return TestClient(tpapp, raise_server_exceptions=True)


def _post_tournament_body(tournament: TCTournament) -> bytes:
    return PostData[TCTournament](cookie=1, data=tournament).model_dump_json().encode()


# --- POST /tournament -------------------------------------------------------


def test_receive_tournament_stores_tournament_in_itc(
    tpclient: TestClient, clictx: CliContext, tournament: TCTournament
) -> None:
    resp = tpclient.post(
        "/tournament",
        content=_post_tournament_body(tournament),
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"].startswith("Received tournament:")

    stored = clictx.itc.get("tournament")
    assert isinstance(stored, TCTournament)
    assert stored.name == tournament.name


# --- POST /squore/result ----------------------------------------------------


def test_squore_result_rejects_non_json(tpclient: TestClient) -> None:
    resp = tpclient.post("/squore/result", content=b"not json at all")
    assert resp.status_code == 422
    assert "do not appear to represent a Squore match result" in resp.json()["detail"]


def test_squore_result_rejects_wrong_schema(tpclient: TestClient) -> None:
    resp = tpclient.post("/squore/result", content=b'{"foo": "bar"}')
    assert resp.status_code == 422


def test_squore_result_success(tpclient: TestClient, mocker: MockerFixture) -> None:
    fake_result = MagicMock(name="SquoreMatchLiveData")
    mocker.patch(
        "tcboard.cli.tptools.SquoreMatchLiveData.model_validate_json",
        return_value=fake_result,
    )
    process = mocker.patch(
        "tcboard.cli.tptools.TCBoard.process_squore_livedata", new=AsyncMock()
    )

    resp = tpclient.post("/squore/result", content=b"{}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"] == "OK"
    assert body["title"] == "Thank you for your diligence!"
    assert "Please leave the tablet at the court." in body["message"]
    process.assert_awaited_once_with(fake_result)


def test_squore_result_board_failure_reports_nok(
    tpclient: TestClient, mocker: MockerFixture
) -> None:
    mocker.patch(
        "tcboard.cli.tptools.SquoreMatchLiveData.model_validate_json",
        return_value=MagicMock(),
    )
    mocker.patch(
        "tcboard.cli.tptools.TCBoard.process_squore_livedata",
        new=AsyncMock(side_effect=RuntimeError("upstream exploded")),
    )

    resp = tpclient.post("/squore/result", content=b"{}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"] == "NOK"
    assert body["title"] == "An error occurred submitting the match result"
    assert "upstream exploded" in body["message"]


# --- setup_for_tptools lifespan --------------------------------------------


@pytest.mark.asyncio
async def test_setup_without_bootstrap_url_sets_no_tournament(
    clictx: CliContext,
) -> None:
    async with setup_for_tptools(clictx) as task:
        assert task is not None
        await task

    assert clictx.itc.get("tournament") is None
    assert any(
        getattr(r, "path", None) == f"{API_MOUNTPOINT}/{TPTOOLS_PATH_VERSION}"
        for r in clictx.api.routes
    )
    assert tpapp.state.clictx is clictx


@pytest.mark.asyncio
async def test_setup_with_bootstrap_url_loads_tournament(
    clictx: CliContext, tournament: TCTournament, mocker: MockerFixture
) -> None:
    fetch = mocker.patch(
        "tcboard.cli.tptools.bootstrap_tournament_from_url",
        new=AsyncMock(return_value=tournament),
    )
    url = URL("http://tcboard/bootstrap")
    async with setup_for_tptools(clictx, load_from_url=url) as task:
        assert task is not None
        await task

    fetch.assert_awaited_once_with(TCTournament, url)
    assert clictx.itc.get("tournament") is tournament


@pytest.mark.asyncio
async def test_setup_records_thank_you_template(
    clictx: CliContext, tmp_path: pathlib.Path
) -> None:
    template = tmp_path / "thanks.html.j2"
    async with setup_for_tptools(clictx, thank_you_template=template) as task:
        assert task is not None
        await task
    assert tpapp.state.thank_you_template == template


@pytest.mark.asyncio
async def test_tptools_plugin_with_options(
    run_plugin: Any,
    clictx: CliContext,
    tournament: TCTournament,
    mocker: MockerFixture,
    tmp_path: pathlib.Path,
) -> None:
    fetch = mocker.patch(
        "tcboard.cli.tptools.bootstrap_tournament_from_url",
        new=AsyncMock(return_value=tournament),
    )
    template = tmp_path / "t.j2"
    async with run_plugin(
        tptools_plugin,
        [
            "--api-mount-point",
            "/custom",
            "--load-from-url",
            "http://tcboard/initial",
            "-t",
            str(template),
        ],
    ) as task:
        await task

    fetch.assert_awaited_once()
    assert clictx.itc.get("tournament") is tournament
    assert any(getattr(r, "path", None) == "/custom/v1" for r in clictx.api.routes)
    assert tpapp.state.thank_you_template == template


@pytest.mark.asyncio
async def test_tptools_plugin_defaults(run_plugin: Any, clictx: CliContext) -> None:
    async with run_plugin(tptools_plugin, []) as task:
        await task
    assert clictx.itc.get("tournament") is None
