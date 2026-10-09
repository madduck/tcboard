import asyncio
import pathlib
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import click
import pytest
from pytest_mock import MockerFixture

from tcboard import TCBoard, TCTournament
from tcboard.cli.db import (
    DEFAULT_SQLITE_PATH,
    OptionalPath,
    database_backend,
    receive_updates,
)
from tcboard.cli.db import (
    db as db_plugin,
)
from tcboard.cli.util import CliContext
from tcboard.dbmanager import DBManager
from tcboard.ext.squore.livedata import SquoreMatchLiveData

from .conftest import cancel, close_if_coro, wait_until

# --- OptionalPath -----------------------------------------------------------


def test_optionalpath_false_means_unset() -> None:
    assert OptionalPath(path_type=pathlib.Path).convert(False, None, None) is None


def test_optionalpath_true_is_usage_error() -> None:
    with pytest.raises(click.BadParameter, match="`true` is not a valid value"):
        OptionalPath(path_type=pathlib.Path).convert(True, None, None)


def test_optionalpath_string_is_normal_path() -> None:
    ret = OptionalPath(path_type=pathlib.Path).convert("some/file.sqlite", None, None)
    assert ret == pathlib.Path("some/file.sqlite")


# --- receive_updates --------------------------------------------------------


@pytest.mark.asyncio
async def test_receive_updates_returns_immediately_if_nothing_to_record(
    clictx: CliContext,
) -> None:
    await receive_updates(clictx, record_tournaments=False, record_livedata=False)


@pytest.mark.asyncio
async def test_receive_updates_skips_unset_sources(
    clictx: CliContext, tournament: TCTournament, mocker: MockerFixture
) -> None:
    """With only the tournament set, the livedata stream yields None first."""
    record_t = mocker.patch.object(DBManager, "record_tournament", new=AsyncMock())
    record_l = mocker.patch.object(DBManager, "record_livedata", new=AsyncMock())
    clictx.itc.set("tournament", tournament)

    async with DBManager(file=None) as dbmgr:
        await dbmgr.init_tables()
        clictx.dbmgr = dbmgr
        task = asyncio.create_task(receive_updates(clictx))
        await wait_until(lambda: record_t.await_count > 0)
        await cancel(task)

    record_t.assert_awaited_with(tournament)
    record_l.assert_not_awaited()


@pytest.mark.asyncio
async def test_receive_updates_records_tournament_and_livedata(
    clictx: CliContext,
    tournament: TCTournament,
    mocker: MockerFixture,
) -> None:
    livedata = MagicMock(spec=SquoreMatchLiveData)
    record_t = mocker.patch.object(DBManager, "record_tournament", new=AsyncMock())
    record_l = mocker.patch.object(DBManager, "record_livedata", new=AsyncMock())

    clictx.itc.set("tournament", tournament)
    clictx.itc.set("squorelivedata", livedata)

    async with DBManager(file=None) as dbmgr:
        await dbmgr.init_tables()
        clictx.dbmgr = dbmgr
        task = asyncio.create_task(receive_updates(clictx))
        await wait_until(lambda: bool(record_t.await_count and record_l.await_count))
        await cancel(task)

    record_t.assert_awaited_with(tournament)
    record_l.assert_awaited_with(livedata)


@pytest.mark.asyncio
async def test_receive_updates_warns_on_unexpected_event(
    clictx: CliContext, mocker: MockerFixture
) -> None:
    warn = mocker.patch("tcboard.cli.db.logger.warning")
    clictx.itc.set("squorelivedata", "not a livedata object")

    async with DBManager(file=None) as dbmgr:
        await dbmgr.init_tables()
        clictx.dbmgr = dbmgr
        task = asyncio.create_task(receive_updates(clictx, record_tournaments=False))
        await wait_until(lambda: warn.called)
        await cancel(task)

    assert "unexpected event" in warn.call_args.args[0]


# --- database_backend (see KNOWN_DB_BUG) ------------------------------------


@pytest.mark.asyncio
async def test_database_backend_restores_board_from_db(
    clictx: CliContext, tcboard: TCBoard, tmp_path: pathlib.Path
) -> None:
    dbfile = tmp_path / "db.sqlite"
    async with DBManager(file=dbfile) as dbmgr:
        await dbmgr.init_tables()
        await dbmgr.record_board_state(tcboard)

    async with database_backend(clictx, file=dbfile) as task:
        close_if_coro(task)

    assert clictx.board.tournament is not None
    assert clictx.board.tournament.name == "test tournament"


@pytest.mark.asyncio
async def test_database_backend_rebuilds_from_tournament_and_livedata(
    clictx: CliContext,
    tournament: TCTournament,
    tmp_path: pathlib.Path,
    mocker: MockerFixture,
) -> None:
    dbfile = tmp_path / "db.sqlite"
    async with DBManager(file=dbfile) as dbmgr:
        await dbmgr.init_tables()
        await dbmgr.record_tournament(tournament)

    async def _ldjson(_self: DBManager) -> AsyncGenerator[str]:
        yield "{}"

    mocker.patch.object(
        DBManager, "get_latest_livedata_json_for_each_match", new=_ldjson
    )
    sqlm = mocker.patch("tcboard.cli.db.SquoreMatchLiveData")
    sqlm.model_validate_json.return_value = "livedata"
    process_ld = mocker.patch.object(
        TCBoard, "process_squore_livedata", new=AsyncMock()
    )
    process_t = mocker.patch.object(TCBoard, "process_tournament", new=AsyncMock())
    update = mocker.patch.object(TCBoard, "update", new=AsyncMock())

    async with database_backend(clictx, file=dbfile) as task:
        close_if_coro(task)

    process_t.assert_awaited_once()
    process_ld.assert_awaited_once_with("livedata")
    update.assert_awaited_once()


@pytest.mark.asyncio
async def test_database_backend_empty_db_does_not_notify(
    clictx: CliContext, tmp_path: pathlib.Path, mocker: MockerFixture
) -> None:
    update = mocker.patch.object(TCBoard, "update", new=AsyncMock())

    async with database_backend(clictx, file=tmp_path / "empty.sqlite") as task:
        close_if_coro(task)

    update.assert_not_called()


@pytest.mark.asyncio
async def test_database_backend_default_file_argument(
    clictx: CliContext, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    async with database_backend(clictx) as task:
        close_if_coro(task)
    assert (tmp_path / DEFAULT_SQLITE_PATH.name).exists()


@pytest.mark.asyncio
async def test_db_plugin_with_file_and_recording_flags(
    run_plugin: Any, tmp_path: pathlib.Path
) -> None:
    dbfile = tmp_path / "plugin.sqlite"
    async with run_plugin(
        db_plugin,
        ["--file", str(dbfile), "--record-tournament-data", "--record-livedata"],
    ) as task:
        close_if_coro(task)
    assert dbfile.exists()


@pytest.mark.asyncio
async def test_db_plugin_default_file_is_created_in_cwd(
    run_plugin: Any, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    async with run_plugin(db_plugin, []) as task:
        close_if_coro(task)
    assert (tmp_path / DEFAULT_SQLITE_PATH.name).exists()


@pytest.mark.asyncio
async def test_database_backend_records_board_state_on_update(
    clictx: CliContext, tmp_path: pathlib.Path
) -> None:
    dbfile = tmp_path / "db.sqlite"
    async with database_backend(clictx, file=dbfile) as task:
        close_if_coro(task)
        await clictx.board._post_update()

    async with DBManager(file=dbfile) as dbmgr:
        cursor = await dbmgr.execute("select count(*) as n from board")
        row = await cursor.fetchone()
    assert row is not None and row["n"] >= 1
