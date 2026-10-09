from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture

from tcboard import TCBoard
from tcboard.alert import Alert
from tcboard.cli.api import (
    API_MOUNTPOINT,
    apiapp,
    configure_api,
)
from tcboard.cli.api import (
    api as api_plugin,
)
from tcboard.cli.util import CliContext
from tcboard.exceptions import EntityNotFoundError
from tcboard.matchstate import MatchState


@pytest.fixture
def apiclient(clictx: CliContext) -> Any:
    apiapp.state.clictx = clictx
    return TestClient(apiapp, raise_server_exceptions=True)


@pytest.fixture
def matchstate_in_board(clictx: CliContext, matchstate: MatchState) -> MatchState:
    clictx.board.matchstates_by_matchid[matchstate.match.id] = matchstate
    return matchstate


def test_root_returns_no_content(apiclient: TestClient) -> None:
    resp = apiclient.get("/")
    assert resp.status_code == 204


def test_courts(apiclient: TestClient) -> None:
    resp = apiclient.get("/courts")
    assert resp.status_code == 200
    assert sorted(c["id"] for c in resp.json()) == [1, 2]


def test_courts_without_tournament_is_424(clictx: CliContext) -> None:
    clictx.board.tournament = None
    apiapp.state.clictx = clictx
    resp = TestClient(apiapp).get("/courts")
    assert resp.status_code == 424


def test_match_ack(apiclient: TestClient, matchstate_in_board: MatchState) -> None:
    assert matchstate_in_board.acked is False
    resp = apiclient.patch(f"/match/ack/{matchstate_in_board.match.id}")
    assert resp.status_code == 204
    assert matchstate_in_board.acked is True


def test_match_unack(apiclient: TestClient, matchstate_in_board: MatchState) -> None:
    matchstate_in_board.acked = True
    resp = apiclient.patch(f"/match/unack/{matchstate_in_board.match.id}")
    assert resp.status_code == 204
    assert matchstate_in_board.acked is False


def test_match_reset(apiclient: TestClient, matchstate_in_board: MatchState) -> None:
    matchstate_in_board.livedata = None
    resp = apiclient.patch(f"/match/reset/{matchstate_in_board.match.id}")
    assert resp.status_code == 204
    assert matchstate_in_board.livedata is None


def test_match_ack_not_found_maps_to_404(
    apiclient: TestClient, mocker: MockerFixture
) -> None:
    mocker.patch.object(
        TCBoard,
        "ack_match",
        new=AsyncMock(
            side_effect=EntityNotFoundError(Alert(text="Match not found to ack/unack"))
        ),
    )
    resp = apiclient.patch("/match/ack/nope")
    assert resp.status_code == 404
    assert "No match with ID nope" in resp.json()["detail"]


def test_match_unack_not_found_maps_to_404(
    apiclient: TestClient, mocker: MockerFixture
) -> None:
    mocker.patch.object(
        TCBoard,
        "ack_match",
        new=AsyncMock(side_effect=EntityNotFoundError(Alert(text="nf"))),
    )
    resp = apiclient.patch("/match/unack/nope")
    assert resp.status_code == 404
    assert "No match with ID nope" in resp.json()["detail"]


def test_match_reset_not_found_maps_to_404(
    apiclient: TestClient, mocker: MockerFixture
) -> None:
    mocker.patch.object(
        TCBoard,
        "reset_match",
        new=AsyncMock(side_effect=EntityNotFoundError(Alert(text="nf"))),
    )
    resp = apiclient.patch("/match/reset/nope")
    assert resp.status_code == 404
    assert "No match with ID nope" in resp.json()["detail"]


def test_alert_clear(apiclient: TestClient, clictx: CliContext) -> None:
    alert = Alert(text="alert")
    clictx.board.handle_error(alert, court=clictx.board.tournament.courts[1])  # type: ignore[union-attr]
    resp = apiclient.patch(f"/alert/clear/1/{alert.id}")
    assert resp.status_code == 204
    assert alert.cleared is not None


def test_alert_clear_not_found_maps_to_404(apiclient: TestClient) -> None:
    alert_id = "3f2d7e3a-1b2c-4d5e-8f90-123456789abc"
    resp = apiclient.patch(f"/alert/clear/1/{alert_id}")
    assert resp.status_code == 404
    assert f"No alert with ID {alert_id} on court with ID 1" in resp.json()["detail"]


def test_configure_api_mounts_under_default_mountpoint(clictx: CliContext) -> None:
    import asyncio

    async def run() -> None:
        async with configure_api(clictx) as task:
            assert task is None

    asyncio.run(run())
    mounts = [r for r in clictx.api.routes if getattr(r, "name", None) == "apiapp"]
    assert len(mounts) == 1
    assert mounts[0].path == f"{API_MOUNTPOINT}/v1"  # type: ignore[attr-defined]
    assert apiapp.state.clictx is clictx


@pytest.mark.asyncio
async def test_api_plugin_with_custom_mountpoint(
    clictx: CliContext, run_plugin: Any
) -> None:
    async with run_plugin(api_plugin, ["--api-mount-point", "/custom"]) as task:
        assert task is None
    assert any(getattr(r, "path", None) == "/custom/v1" for r in clictx.api.routes)


@pytest.mark.parametrize("path", ["/match/ack/nope", "/match/unack/nope"])
def test_unknown_match_id_returns_404(apiclient: TestClient, path: str) -> None:
    resp = TestClient(apiapp, raise_server_exceptions=False).patch(path)
    assert resp.status_code == 404
