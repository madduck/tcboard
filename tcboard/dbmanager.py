import logging
import pathlib
import re
from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from typing import Any, Never, Self

from aiosqlite import Connection, Cursor, Row, connect
from aiosqlite.context import Result
from pydantic import BaseModel
from tptools import Tournament

from .livedata import LiveData

logger = logging.getLogger(__name__)

_TABLE_SQL = re.sub(
    r"\n\s+",
    " ",
    """
    create table if not exists {table} (
        id integer primary key,
        timestamp timestamp not null default(strftime('%F %H:%M:%f')),
        data json not null check (like('{{%}}', data))
    );
""".strip(),
    count=0,
    flags=re.MULTILINE,
)

TABLENAMES = ["squorelivedata", "tournament", "board"]


class DBManager(AbstractAsyncContextManager["DBManager"]):
    def __init__(self, *, file: pathlib.Path | None) -> None:
        self._file = file or ":memory:"
        self._connection: None | Connection = None
        self._stack: AsyncExitStack = AsyncExitStack()

    @staticmethod
    def _sqlite_dict_factory(cursor: Cursor, row: Row) -> dict[str, Any]:
        fields = [column[0] for column in cursor.description]
        return dict(zip(fields, row, strict=True))

    async def __aenter__(self) -> Self:
        logger.debug(f"Connecting to SQLite database {self._file}…")
        # self._db = await aiosqlite.connect(self._dbname, isolation_level=None)
        # GROSS HACK for 0.20.0 https://github.com/omnilib/aiosqlite/issues/290
        _conn_awaitable = connect(self._file, isolation_level=None)
        _conn_awaitable.daemon = True  # type: ignore[attr-defined]
        self._connection = await self._stack.enter_async_context(_conn_awaitable)
        self._connection.row_factory = self._sqlite_dict_factory  # type: ignore[assignment]
        logger.info(f"Connected to SQLite database {self._file}")
        return self

    async def __aexit__(self, *_: Any) -> bool:
        logger.debug(f"Disconnecting from SQLite database {self._file}…")
        await self._stack.aclose()
        self._connection = None
        logger.info(f"Closed connection to SQLite database {self._file}")
        return False

    def execute(
        self, sql: str, params: dict[str, Any] | None = None
    ) -> Never | Result[Cursor]:
        if self._connection is None:
            raise RuntimeError(f"Database is not connected: {self._file}")

        return self._connection.execute(sql, params)

    async def init_tables(self, *, drop_tables: bool = False) -> None:
        for table in TABLENAMES:
            if drop_tables:
                logger.debug(f"Dropping existing table '{table}'")
                await self.execute(f"drop table if exists {table}")
            await self.execute(_TABLE_SQL.format(table=table))
            logger.debug(
                f"Initialised table '{table}' (or made sure it already exists)"
            )

    async def insert_json_record(self, table: str, model: BaseModel) -> int | Never:
        json = model.model_dump_json(round_trip=True)
        cursor = await self.execute(
            f"insert into {table} (data) values (:json) returning id", {"json": json}
        )
        ret = await cursor.fetchone()
        if ret is None:  # pragma no cover — don't know how to test for this
            raise RuntimeError(
                f"Insert record into table '{table}' returned no ID: {model}"
            )
        return int(ret["id"])

    async def record_tournament(self, tournament: Tournament) -> int | None:
        try:
            ret = await self.insert_json_record("tournament", tournament)
            logger.debug(f"Recorded tournament in DB with ID {ret}: {tournament}")
            return ret

        except RuntimeError:  # pragma no cover — don't know how to test for this
            logger.debug(
                "Recorded no tournament, since there wasn't "
                f"anything to record: {tournament!r}"
            )
            return None

    async def record_livedata(self, livedata: LiveData) -> int | None:
        try:
            ret = await self.insert_json_record("squorelivedata", livedata)
            logger.debug(f"Recording live data in DB with ID {ret}: {livedata}")
            return ret

        except RuntimeError:  # pragma no cover — don't know how to test for this
            logger.debug(
                "Recorded no live data, since there wasn't "
                f"anything to record: {livedata!r}"
            )
            return None

        return None

    async def get_latest_tournament_json(self) -> str | None:
        async with self.execute(
            "select * from tournament order by id desc limit 1"
        ) as cursor:
            ret = await cursor.fetchone()
            if ret is None:
                return None

            logger.info(
                "Read from database latest tournament with ID "
                f"{ret['id']} (timestamp: {ret['timestamp']})"
            )
            return str(ret["data"])

    async def get_latest_livedata_json_for_each_match(
        self,
    ) -> AsyncGenerator[str]:
        async with self.execute("""
            select m.matchid, data->>"court" as court, l.* from squorelivedata l
              join json_each(l.data, "$._matchid") j
              join (
                select data->>"_matchid" as matchid,
                       max(id) as highest_id
                  from squorelivedata group by matchid
              ) as m
              on (m.matchid = j.value and m.highest_id = l.id)
              order by l.timestamp;
        """) as cursor:
            async for rec in cursor:
                logger.info(
                    "Read from database latest livedata for match "
                    f"{rec['matchid']} on {rec['court']} "
                    f"(timestamp: {rec['timestamp']})"
                )
                yield rec["data"]

    async def get_all_tournament_and_livedata_records(
        self,
    ) -> AsyncGenerator[dict[str, Any]]:
        async with self.execute(  # TODO:
            "select timestamp, 'tournament' as type, data from tournament "
            "union "
            "select timestamp, 'squorelivedata' as type, data from squorelivedata "
            "order by timestamp"
        ) as cursor:
            async for rec in cursor:
                yield dict(rec)
