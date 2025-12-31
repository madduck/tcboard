import pytest
from pydantic import BaseModel
from tptools import Tournament

from tcboard.dbmanager import TABLENAMES, DBManager
from tcboard.livedata import LiveData
from tcboard.livestatus import LiveStatus

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
    assert (await dbmanager_inited.execute(f"select * from {tablename}")).lastrowid == 0
    await dbmanager_inited.execute(f"insert into {tablename} (data) values ('{{}}')")
    await dbmanager_inited.init_tables(drop_tables=drop)
    curs = await dbmanager_inited.execute(f"select count(*) from {tablename}")
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
async def test_record_tournament(dbmanager_inited: DBManager) -> None:
    assert await dbmanager_inited.record_tournament(Tournament()) == 1


@pytest.mark.asyncio
async def test_record_livedata(
    dbmanager_inited: DBManager, FakeLiveDataFactory: FakeLiveDataFactoryType
) -> None:
    assert await dbmanager_inited.record_livedata(FakeLiveDataFactory()) == 1


@pytest.mark.asyncio
async def test_get_last_tournament_empty(dbmanager_inited: DBManager) -> None:
    tourn = await dbmanager_inited.get_latest_tournament_json()
    assert tourn is None


@pytest.mark.asyncio
async def test_get_last_tournament(dbmanager_inited: DBManager) -> None:
    await dbmanager_inited.record_tournament(Tournament(name="one"))
    await dbmanager_inited.record_tournament(Tournament(name="two"))

    json = await dbmanager_inited.get_latest_tournament_json()
    assert json is not None
    tourn = Tournament.model_validate_json(json)
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
async def test_get_all_tournament_and_livedata_records(
    dbmanager_inited: DBManager, FakeLiveDataFactory: FakeLiveDataFactoryType
) -> None:
    await dbmanager_inited.record_tournament(Tournament(name="one"))
    await dbmanager_inited.record_tournament(Tournament(name="two"))

    for matchid in ("one", "two", "three"):
        for status in (LiveStatus.READY, LiveStatus.ONGOING):
            await dbmanager_inited.record_livedata(
                FakeLiveDataFactory(matchid=matchid, status=status)
            )

    ret = [r async for r in dbmanager_inited.get_all_tournament_and_livedata_records()]

    assert len([r for r in ret if r["type"] == "squorelivedata"]) == 2 * 3
    assert len([r for r in ret if r["type"] == "tournament"]) == 2
