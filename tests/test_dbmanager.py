import pytest
from pydantic import BaseModel

from tcboard.apicall import APICall
from tcboard.board import TCBoard
from tcboard.dbmanager import TABLENAMES, DBManager
from tcboard.devinfo import DeviceInfo
from tcboard.ext.squore.devinfo import SquoreDeviceInfo
from tcboard.livedata import LiveData
from tcboard.livestatus import LiveStatus
from tcboard.tournament import TCTournament

from .conftest import (
    FakeLiveData,
    FakeLiveDataFactoryType,
)


@pytest.fixture
def livedata(FakeLiveDataFactory: FakeLiveDataFactoryType) -> LiveData:
    return FakeLiveDataFactory()


@pytest.mark.asyncio
async def test_init_tables_not_connected() -> None:
    dbmanager = DBManager(file=None)
    with pytest.raises(RuntimeError, match="Database is not connected"):
        await dbmanager.init_tables()


@pytest.mark.asyncio
async def test_init_tables(dbmanager: DBManager) -> None:
    await dbmanager.init_tables()

    ret = await dbmanager.execute("select name from sqlite_master where type = 'table'")
    tablenames = [pair["name"] for pair in await ret.fetchall()]

    for tablename in TABLENAMES:
        assert tablename in tablenames


@pytest.mark.parametrize("tablename", TABLENAMES)
@pytest.mark.parametrize("drop, count", [(True, 0), (False, 1)])
@pytest.mark.asyncio
async def test_init_tables_idempotent(
    dbmanager_inited: DBManager, drop: bool, count: int, tablename: str
) -> None:
    assert (await dbmanager_inited.execute(f"select * from {tablename}")).lastrowid == 0  # nosec: B608
    await dbmanager_inited.execute(f"insert into {tablename} (data) values ('{{}}')")  # nosec: B608
    await dbmanager_inited.init_tables(drop_tables=drop)
    curs = await dbmanager_inited.execute(f"select count(*) from {tablename}")  # nosec: B608
    async for row in curs:
        assert row["count(*)"] == count
        break

    else:
        raise AssertionError(f"Query of table {tablename} returned no results")


@pytest.mark.parametrize("tablename", TABLENAMES)
@pytest.mark.asyncio
async def test_insert_json_record(tablename: str, dbmanager_inited: DBManager) -> None:
    class EmptyModel(BaseModel): ...

    assert await dbmanager_inited.insert_json_record(tablename, EmptyModel()) == 1


@pytest.mark.asyncio
async def test_insert_json_record_rejects_quoted_table(
    dbmanager_inited: DBManager,
) -> None:
    class EmptyModel(BaseModel): ...

    with pytest.raises(ValueError, match='table cannot contain `"`'):
        await dbmanager_inited.insert_json_record('tab"le', EmptyModel())


@pytest.mark.asyncio
async def test_record_tournament(dbmanager_inited: DBManager) -> None:
    assert await dbmanager_inited.record_tournament(TCTournament()) == 1


@pytest.mark.asyncio
async def test_record_livedata(
    dbmanager_inited: DBManager, FakeLiveDataFactory: FakeLiveDataFactoryType
) -> None:
    assert await dbmanager_inited.record_livedata(FakeLiveDataFactory()) == 1


@pytest.mark.asyncio
async def test_record_devinfo(
    dbmanager_inited: DBManager, deviceinfo: DeviceInfo
) -> None:
    assert await dbmanager_inited.record_devinfo(deviceinfo) == 1


@pytest.mark.asyncio
async def test_record_apicall(dbmanager_inited: DBManager, apicall: APICall) -> None:
    assert await dbmanager_inited.record_apicall(apicall) == 1


@pytest.mark.asyncio
async def test_get_last_tournament_empty(dbmanager_inited: DBManager) -> None:
    tourn = await dbmanager_inited.get_latest_tournament_json()
    assert tourn is None


@pytest.mark.asyncio
async def test_get_last_tournament(dbmanager_inited: DBManager) -> None:
    await dbmanager_inited.record_tournament(TCTournament(name="one"))
    await dbmanager_inited.record_tournament(TCTournament(name="two"))

    json = await dbmanager_inited.get_latest_tournament_json()
    assert json is not None
    tourn = TCTournament.model_validate_json(json)
    assert tourn is not None
    assert tourn.name == "two"


@pytest.mark.asyncio
async def test_get_last_livedata(
    dbmanager_inited: DBManager, FakeLiveDataFactory: FakeLiveDataFactoryType
) -> None:
    for matchid in ("one", "two", "three"):
        for status in (LiveStatus.READY, LiveStatus.ONGOING):
            await dbmanager_inited.record_livedata(
                FakeLiveDataFactory(matchid=matchid, status=status)
            )

    seen = set()
    async for json in dbmanager_inited.get_latest_livedata_json_for_each_match():
        livedata = FakeLiveData.make_model_instance_json(json)
        assert livedata.status == LiveStatus.ONGOING
        seen.add(livedata.matchid)

    assert len(seen) == 3


@pytest.mark.asyncio
async def test_get_latest_devinfo(
    dbmanager_inited: DBManager, deviceinfo: DeviceInfo
) -> None:
    await dbmanager_inited.record_devinfo(deviceinfo)
    await dbmanager_inited.record_devinfo(deviceinfo)

    seen = [json async for json in dbmanager_inited.get_latest_devinfo_json()]

    assert len(seen) == 1
    latest = DeviceInfo.model_validate_json(seen[0])
    assert latest.deviceid == deviceinfo.deviceid


@pytest.mark.asyncio
async def test_get_all_stream_records(
    dbmanager_inited: DBManager, FakeLiveDataFactory: FakeLiveDataFactoryType
) -> None:
    await dbmanager_inited.record_tournament(TCTournament(name="one"))
    await dbmanager_inited.record_tournament(TCTournament(name="two"))

    for matchid in ("one", "two", "three"):
        for status in (LiveStatus.READY, LiveStatus.ONGOING):
            await dbmanager_inited.record_livedata(
                FakeLiveDataFactory(matchid=matchid, status=status)
            )

    for devid in ("one", "two", "three"):
        await dbmanager_inited.record_devinfo(
            SquoreDeviceInfo(
                deviceid=devid, batteryCharging=False, batteryPercentage=100
            )
        )

    ret = [r async for r in dbmanager_inited.get_all_stream_records()]

    assert len([r for r in ret if r["type"] == "squoredevinfo"]) == 3
    assert len([r for r in ret if r["type"] == "squorelivedata"]) == 2 * 3
    assert len([r for r in ret if r["type"] == "tournament"]) == 2


@pytest.mark.asyncio
async def test_get_all_records_keeps_identical_tournaments(
    dbmanager_inited: DBManager,
) -> None:
    # Identical records must not be deduplicated: replaying the same tournament
    # twice is a valid event stream.  A plain UNION would drop the duplicate.
    await dbmanager_inited.record_tournament(TCTournament(name="same"))
    await dbmanager_inited.record_tournament(TCTournament(name="same"))

    ret = [r async for r in dbmanager_inited.get_all_stream_records()]

    assert len([r for r in ret if r["type"] == "tournament"]) == 2


@pytest.mark.asyncio
async def test_record_boardstate(dbmanager_inited: DBManager, tcboard: TCBoard) -> None:
    assert await dbmanager_inited.record_board_state(tcboard) == 1


@pytest.mark.asyncio
async def test_record_boardstate_doesnt_alter_alerts_dict(
    dbmanager_inited: DBManager, tcboard: TCBoard
) -> None:
    alerts = tcboard.alerts_by_courtid.copy()
    await dbmanager_inited.record_board_state(tcboard)
    assert alerts == tcboard.alerts_by_courtid


@pytest.mark.asyncio
async def test_get_last_board_state_empty(dbmanager_inited: DBManager) -> None:
    board = await dbmanager_inited.get_last_board()
    assert board is None


@pytest.mark.asyncio
async def test_get_last_board_state(
    dbmanager_inited: DBManager, tcboard: TCBoard
) -> None:
    await dbmanager_inited.record_board_state(tcboard)
    board = await dbmanager_inited.get_last_board()
    assert board == tcboard
