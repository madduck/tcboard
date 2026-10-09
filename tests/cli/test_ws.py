import asyncio
import json
import pathlib
from typing import Any
from unittest.mock import MagicMock

import pytest
from click_async_plugins import ITC
from fastapi import FastAPI, HTTPException
from fastapi.datastructures import URL, Address, Headers
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture
from starlette.websockets import WebSocketDisconnect
from tptools import Court
from tptools.namepolicy import (
    ClubNamePolicy,
    CountryNamePolicy,
    CourtNamePolicy,
    DrawNamePolicy,
    DrawNamePolicyParams,
    PairCombinePolicy,
    PlayerNamePolicy,
)

from tcboard import TCBoard
from tcboard.cli.api import apiapp
from tcboard.cli.util import CliContext
from tcboard.cli.ws import (
    WS_PATH_VERSION,
    CourtData,
    DisplayData,
    WSHandler,
    configure_for_websockets,
    get_dev_map,
    get_devmap_path,
    get_drawnamepolicy,
    get_remote,
    get_schema,
    get_websocket_peer,
    interval_generator,
    process_tcboard_event,
)
from tcboard.cli.ws import (
    websocket as ws_endpoint,
)
from tcboard.cli.ws import (
    ws as ws_plugin,
)
from tcboard.exceptions import TournamentNotLoaded

from .conftest import wait_until

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class FakeWebSocket:
    """Just enough of starlette's WebSocket for the endpoint under test."""

    def __init__(self, app: FastAPI) -> None:
        self.app = app
        self.url = URL("ws://testserver/ws/v1/")
        self.base_url = URL("ws://testserver/")
        self.client = Address("192.0.2.7", 5555)
        self.headers: Headers = Headers({})
        self.sent_text: list[str] = []
        self.sent_json: list[Any] = []
        self.closed_with: str | None = None
        self.incoming: asyncio.Queue[Any] = asyncio.Queue()

    async def accept(self) -> None:
        return None

    async def receive_text(self) -> str:
        item = await self.incoming.get()
        if isinstance(item, BaseException):
            raise item
        return str(item)

    async def send_text(self, data: str) -> None:
        self.sent_text.append(data)

    async def send_json(self, data: Any) -> None:
        self.sent_json.append(data)

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        self.closed_with = reason


def make_ws_clictx(board: TCBoard | None) -> CliContext:
    itc = ITC()
    if board is not None:
        itc.set("board", board)
    clictx = CliContext(itc=itc)
    clictx.api.mount("/api/v1", app=apiapp, name="apiapp")
    return clictx


def default_policies() -> dict[str, Any]:
    return {
        "drawnamepolicy": DrawNamePolicy(),
        "courtnamepolicy": CourtNamePolicy(),
        "playernamepolicy": PlayerNamePolicy(),
        "paircombinepolicy": PairCombinePolicy(),
        "countrynamepolicy": CountryNamePolicy(),
        "clubnamepolicy": ClubNamePolicy(),
    }


def start_endpoint(ws: FakeWebSocket, handler: WSHandler) -> asyncio.Task[None]:
    return asyncio.create_task(ws_endpoint(ws, handler, **default_policies()))  # type: ignore[arg-type]


async def end_session(ws: FakeWebSocket, task: asyncio.Task[None]) -> None:
    await ws.incoming.put(WebSocketDisconnect())
    await asyncio.wait_for(task, timeout=2)


@pytest.fixture
def board(tcboard: TCBoard) -> TCBoard:
    return tcboard


@pytest.fixture
def wsclictx(board: TCBoard) -> CliContext:
    return make_ws_clictx(board)


@pytest.fixture
def wsocket(wsclictx: CliContext) -> FakeWebSocket:
    return FakeWebSocket(wsclictx.api)


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------


def test_get_remote_uses_forwarded_header(httpcon: MagicMock) -> None:
    httpcon.headers = Headers({"X-Forwarded-For": "198.51.100.9"})
    assert get_remote(httpcon) == "198.51.100.9"


def test_get_remote_falls_back_to_client_host(httpcon: MagicMock) -> None:
    httpcon.client = Address("192.0.2.1", 1)
    assert get_remote(httpcon) == "192.0.2.1"


def test_get_remote_unknown_when_no_client(httpcon: MagicMock) -> None:
    assert get_remote(httpcon) == "(unknown)"


def test_get_websocket_peer_none() -> None:
    assert get_websocket_peer(None) is None


def test_get_websocket_peer_with_client(wsocket: FakeWebSocket) -> None:
    assert get_websocket_peer(wsocket) == "192.0.2.7:5555"  # type: ignore[arg-type]


def test_get_websocket_peer_without_client_port(wsocket: FakeWebSocket) -> None:
    wsocket.client = None  # type: ignore[assignment]
    assert get_websocket_peer(wsocket) == "(unknown):0"  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_interval_generator_without_interval_yields_once() -> None:
    async with interval_generator(interval=None, yld="once").stream() as s:
        items = [x async for x in s]
    assert items == ["once"]


@pytest.mark.asyncio
async def test_interval_generator_skip_applies() -> None:
    async with interval_generator(interval=None, yld="once", skip=1).stream() as s:
        items = [x async for x in s]
    assert items == []


@pytest.mark.asyncio
async def test_interval_generator_repeats() -> None:
    collected: list[str] = []
    async with interval_generator(interval=0.001, yld="tick", skip=1).stream() as s:
        async for item in s:
            collected.append(item)
            if len(collected) == 3:
                break
    assert collected == ["tick", "tick", "tick"]


def test_get_devmap_path_missing_state_is_500(httpcon: MagicMock) -> None:
    httpcon.app = FastAPI()
    with pytest.raises(HTTPException) as exc:
        get_devmap_path(httpcon)
    assert exc.value.status_code == 500


def test_get_devmap_path_missing_key_is_500(httpcon: MagicMock) -> None:
    httpcon.app = FastAPI()
    httpcon.app.state.tcboard = {}
    with pytest.raises(HTTPException) as exc:
        get_devmap_path(httpcon)
    assert exc.value.status_code == 500


def test_get_devmap_path_returns_configured_path(
    httpcon: MagicMock, tmp_path: pathlib.Path
) -> None:
    httpcon.app = FastAPI()
    httpcon.app.state.tcboard = {"devmap": tmp_path / "x.toml"}
    assert get_devmap_path(httpcon) == tmp_path / "x.toml"


def test_get_dev_map_reads_toml(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "devmap.toml"
    path.write_text('"172.21.22.34" = "C6"\n')
    devmap = get_dev_map(path)
    assert devmap._devmap == {"172.21.22.34": "C6"}


def test_get_dev_map_missing_file_is_empty(
    tmp_path: pathlib.Path, mocker: MockerFixture
) -> None:
    warn = mocker.patch("tcboard.cli.ws.logger.warning")
    devmap = get_dev_map(tmp_path / "does-not-exist.toml")
    assert devmap._devmap == {}
    assert "not found" in warn.call_args.args[0]


def test_get_drawnamepolicy_builds_policy() -> None:
    policy = get_drawnamepolicy(DrawNamePolicyParams())
    assert isinstance(policy, DrawNamePolicy)


def test_courtdata_exposes_court_id(court1: Court) -> None:
    cd = CourtData(court=court1, label="Court A")
    dumped = cd.model_dump()
    assert dumped["id"] == court1.id
    assert dumped["label"] == "Court A"


def test_displaydata_serializer_filters_by_courtids(
    board: TCBoard,
) -> None:
    states = list(board.get_courtstates_by_court().values())
    data = DisplayData(rev=board.rev, courtstates=states)

    everything = json.loads(data.model_dump_json())
    assert len(everything["courtstates"]) == len(states)

    only_court1 = json.loads(data.model_dump_json(context={"courtids": [1]}))
    ids = [cs["courtid"] for cs in only_court1["courtstates"]]
    assert ids == [1]


def test_process_tcboard_event_detects_change(board: TCBoard) -> None:
    first = process_tcboard_event(board, None)
    assert isinstance(first, DisplayData)
    # identical state -> no new data
    assert process_tcboard_event(board, first) is None
    # changed revision -> new data
    board.rev += 1
    second = process_tcboard_event(board, first)
    assert second is not None and second.rev == board.rev


@pytest.mark.asyncio
async def test_schema_endpoint() -> None:
    resp = await get_schema()
    assert isinstance(resp, JSONResponse)
    schema = json.loads(bytes(resp.body))
    assert "courtstates" in schema["properties"]


# ---------------------------------------------------------------------------
# WSHandler
# ---------------------------------------------------------------------------


def test_wshandler_unconnected_properties() -> None:
    handler = WSHandler(courtids=[1], timeout=2.0, at_most_every=0.5)
    assert handler.url is None
    assert handler.peer is None
    assert "courts=[1]" in handler.connstr
    assert "timeout=2.0" in handler.connstr


@pytest.mark.asyncio
async def test_wshandler_disconnect_noop_when_not_connected() -> None:
    await WSHandler().disconnect(reason="whatever")


@pytest.mark.asyncio
async def test_wshandler_send_data_requires_connection(board: TCBoard) -> None:
    with pytest.raises(RuntimeError, match="non-existent web socket"):
        await WSHandler().send_data(DisplayData())


@pytest.mark.asyncio
async def test_wshandler_send_welcome_requires_connection() -> None:
    with pytest.raises(RuntimeError, match="non-existent web socket"):
        await WSHandler().send_welcome()


def test_wshandler_events_without_stream_is_empty() -> None:
    async def collect() -> list[Any]:
        return [x async for x in WSHandler().events()]

    assert asyncio.run(collect()) == []


def test_wshandler_make_instance() -> None:
    handler = WSHandler.make_instance(court=[1, 2], timeout=0.5, at_most_every=1.0)
    assert handler.courtids == [1, 2]
    assert handler.timeout == 0.5
    assert handler.at_most_every == 1.0


@pytest.mark.asyncio
async def test_wshandler_disconnect_closes_socket(wsclictx: CliContext) -> None:
    ws = FakeWebSocket(wsclictx.api)
    handler = WSHandler()
    async with handler.accept(ws):  # type: ignore[arg-type]
        assert handler.url == ws.url
        assert handler.peer == "192.0.2.7:5555"
        await handler.disconnect(reason="bye")
    assert ws.closed_with == "bye"
    assert handler.url is None


@pytest.mark.asyncio
async def test_wshandler_send_data_respects_courtids(
    wsclictx: CliContext, board: TCBoard
) -> None:
    ws = FakeWebSocket(wsclictx.api)
    handler = WSHandler(courtids=[2])
    async with handler.accept(ws):  # type: ignore[arg-type]
        data = DisplayData(
            rev=1, courtstates=list(board.get_courtstates_by_court().values())
        )
        await handler.send_data(data, courtnamepolicy=CourtNamePolicy())

    assert len(ws.sent_text) == 1
    courtids = [cs["courtid"] for cs in json.loads(ws.sent_text[0])["courtstates"]]
    assert courtids == [2]


@pytest.mark.asyncio
async def test_wshandler_send_welcome_contains_schema_and_apiurl(
    wsclictx: CliContext,
) -> None:
    ws = FakeWebSocket(wsclictx.api)
    handler = WSHandler()
    async with handler.accept(ws):  # type: ignore[arg-type]
        await handler.send_welcome()
    welcome = ws.sent_json[0]
    assert "schema" in welcome
    assert welcome["apiurl"].endswith("/api/v1")


# ---------------------------------------------------------------------------
# websocket endpoint (driven directly, with controlled ITC events)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_endpoint_sends_welcome_then_board(
    wsclictx: CliContext, wsocket: FakeWebSocket
) -> None:
    handler = WSHandler()
    task = start_endpoint(wsocket, handler)
    await wait_until(lambda: len(wsocket.sent_text) == 1 and bool(wsocket.sent_json))

    assert "schema" in wsocket.sent_json[0]
    board_json = json.loads(wsocket.sent_text[0])
    assert "courtstates" in board_json
    await end_session(wsocket, task)
    assert wsclictx.websockets == []


@pytest.mark.asyncio
async def test_endpoint_skips_unchanged_board(
    wsclictx: CliContext, wsocket: FakeWebSocket, board: TCBoard
) -> None:
    task = start_endpoint(wsocket, WSHandler())
    await wait_until(lambda: len(wsocket.sent_text) == 1)

    wsclictx.itc.set("board", board)  # same state again
    await asyncio.sleep(0.05)
    assert len(wsocket.sent_text) == 1

    await end_session(wsocket, task)


@pytest.mark.asyncio
async def test_endpoint_sends_changed_board(
    wsclictx: CliContext, wsocket: FakeWebSocket, board: TCBoard
) -> None:
    task = start_endpoint(wsocket, WSHandler())
    await wait_until(lambda: len(wsocket.sent_text) == 1)

    board.rev += 1
    wsclictx.itc.set("board", board)
    await wait_until(lambda: len(wsocket.sent_text) == 2)
    assert json.loads(wsocket.sent_text[1])["rev"] == board.rev

    await end_session(wsocket, task)


@pytest.mark.asyncio
async def test_endpoint_timeout_resends_board(
    wsclictx: CliContext, wsocket: FakeWebSocket
) -> None:
    task = start_endpoint(wsocket, WSHandler(timeout=0.01))
    await wait_until(lambda: len(wsocket.sent_text) >= 3)
    await end_session(wsocket, task)


@pytest.mark.asyncio
async def test_endpoint_logs_client_messages(
    wsclictx: CliContext, wsocket: FakeWebSocket, mocker: MockerFixture
) -> None:
    debug = mocker.patch("tcboard.cli.ws.logger.debug")
    task = start_endpoint(wsocket, WSHandler())
    await wait_until(lambda: len(wsocket.sent_text) == 1)

    await wsocket.incoming.put("ping from client")
    await wait_until(
        lambda: any("sent: ping" in str(c.args[0]) for c in debug.call_args_list)
    )
    await end_session(wsocket, task)


@pytest.mark.asyncio
async def test_endpoint_without_board_warns_and_sends_nothing(
    mocker: MockerFixture,
) -> None:
    clictx = make_ws_clictx(board=None)
    ws = FakeWebSocket(clictx.api)
    warn = mocker.patch("tcboard.cli.ws.logger.warning")

    task = start_endpoint(ws, WSHandler(timeout=0.01))
    await wait_until(
        lambda: any("No board loaded" in str(c.args[0]) for c in warn.call_args_list)
    )
    await wait_until(
        lambda: any("Board is None" in str(c.args[0]) for c in warn.call_args_list)
    )
    assert ws.sent_text == []
    await end_session(ws, task)


@pytest.mark.asyncio
async def test_endpoint_warns_on_unexpected_board_value(
    wsclictx: CliContext, wsocket: FakeWebSocket, mocker: MockerFixture
) -> None:
    warn = mocker.patch("tcboard.cli.ws.logger.warning")
    task = start_endpoint(wsocket, WSHandler())
    await wait_until(lambda: len(wsocket.sent_text) == 1)

    wsclictx.itc.set("board", 42)  # not str (-> client msg) nor TCBoard
    await wait_until(
        lambda: any("Unexpected event" in str(c.args[0]) for c in warn.call_args_list)
    )
    await end_session(wsocket, task)


@pytest.mark.asyncio
async def test_endpoint_tournament_not_loaded_is_tolerated(
    wsclictx: CliContext,
    wsocket: FakeWebSocket,
    board: TCBoard,
    mocker: MockerFixture,
) -> None:
    warn = mocker.patch("tcboard.cli.ws.logger.warning")
    task = start_endpoint(wsocket, WSHandler())
    await wait_until(lambda: len(wsocket.sent_text) == 1)

    mocker.patch(
        "tcboard.cli.ws.process_tcboard_event",
        side_effect=TournamentNotLoaded("no tournament"),
    )
    wsclictx.itc.set("board", board)
    await wait_until(
        lambda: any(
            "No tournament loaded" in str(c.args[0]) for c in warn.call_args_list
        )
    )
    await end_session(wsocket, task)


@pytest.mark.asyncio
async def test_endpoint_ignores_board_when_data_unchanged(
    wsclictx: CliContext,
    wsocket: FakeWebSocket,
    board: TCBoard,
    mocker: MockerFixture,
) -> None:
    task = start_endpoint(wsocket, WSHandler())
    await wait_until(lambda: len(wsocket.sent_text) == 1)

    mocker.patch("tcboard.cli.ws.process_tcboard_event", return_value=None)
    wsclictx.itc.set("board", board)
    await asyncio.sleep(0.05)
    assert len(wsocket.sent_text) == 1
    await end_session(wsocket, task)


@pytest.mark.asyncio
async def test_endpoint_client_disconnect_is_handled(
    wsclictx: CliContext, wsocket: FakeWebSocket, mocker: MockerFixture
) -> None:
    debug = mocker.patch("tcboard.cli.ws.logger.debug")
    task = start_endpoint(wsocket, WSHandler())
    await wait_until(lambda: len(wsocket.sent_text) == 1)
    await end_session(wsocket, task)
    assert any("disconnected remotely" in str(c.args[0]) for c in debug.call_args_list)


@pytest.mark.asyncio
async def test_endpoint_filters_courts(
    wsclictx: CliContext, wsocket: FakeWebSocket
) -> None:
    task = start_endpoint(wsocket, WSHandler(courtids=[1]))
    await wait_until(lambda: len(wsocket.sent_text) == 1)
    payload = json.loads(wsocket.sent_text[0])
    courtids = [cs["courtid"] for cs in payload["courtstates"]]
    assert courtids == [1]
    await end_session(wsocket, task)


# ---------------------------------------------------------------------------
# configuration / plugin
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_configure_for_websockets_mounts_and_stores_devmap(
    clictx: CliContext, tmp_path: pathlib.Path
) -> None:
    devmap = tmp_path / "map.toml"
    async with configure_for_websockets(
        clictx, devmap_toml=devmap, api_mount_point="/wsx"
    ) as task:
        assert task is None
    assert any(
        getattr(r, "path", None) == f"/wsx/{WS_PATH_VERSION}" for r in clictx.api.routes
    )


@pytest.mark.asyncio
async def test_ws_plugin_options(
    run_plugin: Any, clictx: CliContext, tmp_path: pathlib.Path
) -> None:
    devmap = tmp_path / "plugin-map.toml"
    async with run_plugin(
        ws_plugin,
        ["--devmap-toml", str(devmap), "--api-mount-point", "/plug"],
    ) as task:
        assert task is None
    assert any(
        getattr(r, "path", None) == f"/plug/{WS_PATH_VERSION}"
        for r in clictx.api.routes
    )


# ---------------------------------------------------------------------------
# end-to-end over a real TestClient websocket
# ---------------------------------------------------------------------------


def test_real_websocket_round_trip(board: TCBoard) -> None:
    from tcboard.cli.ws import wsapp

    clictx = make_ws_clictx(board)
    wsapp.state.clictx = clictx
    wsapp.state.tcboard = {"devmap": pathlib.Path("/nonexistent/devmap.toml")}
    clictx.api.mount(f"/ws/{WS_PATH_VERSION}", app=wsapp, name="wsapp")

    client = TestClient(clictx.api)
    with client.websocket_connect(f"/ws/{WS_PATH_VERSION}/") as conn:
        welcome = conn.receive_json()
        assert "schema" in welcome
        assert welcome["apiurl"].endswith("/api/v1")
        assert "courtstates" in json.loads(conn.receive_text())
