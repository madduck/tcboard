import asyncio
import pathlib
import sys
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiosqlite import Row
from pytest_mock import MockerFixture

from tcboard import TCBoard, TCTournament
from tcboard.alert import Alert
from tcboard.cli.replay import (
    DEFAULT_SQLITE_PATH,
    _replay_events,
    _sqlite_dict_factory,
    database_backend,
)
from tcboard.cli.replay import (
    replay as replay_plugin,
)
from tcboard.cli.util import CliContext
from tcboard.dbmanager import DBManager

from .conftest import close_if_coro


@pytest.fixture
def fake_ipdb(mocker: MockerFixture) -> MagicMock:
    fake = MagicMock(name="ipdb")
    mocker.patch.dict(sys.modules, {"ipdb": fake})
    return fake


@pytest.fixture
def dbfile(tmp_path: pathlib.Path) -> pathlib.Path:
    return tmp_path / "replay.sqlite"


def test_sqlite_dict_factory() -> None:
    cursor = MagicMock()
    cursor.description = [("id",), ("data",)]
    row = cast(Row, (7, "x"))
    assert _sqlite_dict_factory(cursor, row) == {"id": 7, "data": "x"}


def test_default_path_is_relative_db_sqlite() -> None:
    assert DEFAULT_SQLITE_PATH == pathlib.Path("./db.sqlite")


@pytest.mark.asyncio
async def test_replay_events_empty_db_is_noop(
    clictx: CliContext, dbfile: pathlib.Path
) -> None:
    async with DBManager(file=dbfile) as db:
        await db.init_tables()
        await _replay_events(clictx, db, speed=1000)
    assert clictx.board.tournament is not None  # untouched fixture board


@pytest.mark.asyncio
async def test_replay_events_replays_tournament(
    clictx: CliContext,
    tournament: TCTournament,
    dbfile: pathlib.Path,
    mocker: MockerFixture,
) -> None:
    async with DBManager(file=dbfile) as db:
        await db.init_tables()
        await db.record_tournament(tournament)

        clictx.board.tournament = None
        process = mocker.spy(TCBoard, "process_tournament")
        await _replay_events(clictx, db, speed=1000)

    process.assert_awaited_once()
    replayed = process.call_args.args[1]
    assert isinstance(replayed, TCTournament)
    assert replayed.name == tournament.name


@pytest.mark.asyncio
async def test_replay_events_replays_multiple_records_with_delays(
    clictx: CliContext,
    tournament: TCTournament,
    dbfile: pathlib.Path,
    mocker: MockerFixture,
) -> None:
    async with DBManager(file=dbfile) as db:
        await db.init_tables()
        await db.record_tournament(tournament)
        await db.record_tournament(tournament)
        # Two rows with explicit, different timestamps so that a delay is computed
        await db.execute(
            "insert into squorelivedata (timestamp, data) values "
            "('2020-01-01 00:00:00.000', '{}'), ('2020-01-01 00:00:02.000', '{}')"
        )
        sleep = mocker.patch("tcboard.cli.replay.asyncio.sleep", new=AsyncMock())
        live = mocker.patch("tcboard.cli.replay.SquoreMatchLiveData")
        live.model_validate_json.return_value = "livedata-stub"
        process_ld = mocker.patch.object(
            TCBoard, "process_squore_livedata", new=AsyncMock()
        )
        mocker.patch.object(TCBoard, "process_tournament", new=AsyncMock())

        await _replay_events(clictx, db, speed=2)

    delays = [c.args[0] for c in sleep.await_args_list]
    assert len(delays) == 4
    # the squorelivedata rows are 2s apart at speed 2 -> 1s sleep; the first record
    # of each stream has no previous timestamp so waits 0s
    assert 1.0 in delays
    process_ld.assert_awaited_with("livedata-stub")


@pytest.mark.asyncio
async def test_replay_events_does_not_enter_debugger_on_alert_change(
    clictx: CliContext,
    tournament: TCTournament,
    dbfile: pathlib.Path,
    mocker: MockerFixture,
    fake_ipdb: MagicMock,
) -> None:
    async with DBManager(file=dbfile) as db:
        await db.init_tables()
        await db.record_tournament(tournament)

        court = tournament.courts[1]

        async def _process_and_raise_alert(
            board: TCBoard, _tournament: TCTournament
        ) -> None:
            board.handle_error(Alert(text="boom"), court=court)

        mocker.patch.object(TCBoard, "process_tournament", new=_process_and_raise_alert)
        await _replay_events(clictx, db, speed=1000)

    fake_ipdb.set_trace.assert_not_called()
    assert clictx.board.alerts_by_courtid[court.id]


@pytest.mark.asyncio
async def test_database_backend_yields_replay_coroutine(
    clictx: CliContext, dbfile: pathlib.Path
) -> None:
    async with DBManager(file=dbfile) as db:
        await db.init_tables()
    async with database_backend(clictx, file=dbfile, speed=1000) as task:
        assert asyncio.iscoroutine(task)
        close_if_coro(task)


@pytest.mark.asyncio
async def test_replay_plugin(
    run_plugin: Any, dbfile: pathlib.Path, mocker: MockerFixture
) -> None:
    async with DBManager(file=dbfile) as db:
        await db.init_tables()
    async with run_plugin(
        replay_plugin, ["--file", str(dbfile), "--speed", "1000"]
    ) as task:
        close_if_coro(task)
