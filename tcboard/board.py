# needed < 3.14 so that annotations aren't evaluated
from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Iterable, MutableMapping, Never, Protocol, cast

import ipdb
from pydantic import (
    UUID4,
    SerializerFunctionWrapHandler,
    ValidatorFunctionWrapHandler,
    field_serializer,
    field_validator,
)
from tabulate import tabulate
from tptools import Court, MatchStatus
from tptools.basemodel import BaseModel

from .alert import Alert
from .courtstate import CourtState
from .devinfo import BatteryStatus, DeviceInfo
from .exceptions import (
    EntityNotFoundError,
    TCBoardException,
    TournamentNotLoaded,
)
from .livedata import LiveData
from .matchslot import MatchSlot
from .matchstate import MatchState
from .tournament import TCTournament

logger = logging.getLogger(__name__)

_NONEXISTENT = object()


class UpdateCallable(Protocol):
    async def __call__(self, board: TCBoard, **updates: Any) -> None: ...


class TCBoard(BaseModel[None]):
    # TODO: the reason this is a BaseModel is because we dump JSON to the database to
    # keep track of state (in case of crashes etc.). This seems like crossing the street
    # to avoid ORM. Consider switching this to SQLModel?
    rev: int = 0
    tournament: TCTournament | None = None
    matchstates_by_matchid: dict[str, MatchState] = {}
    court_by_deviceid: dict[str, Court | None] = {}
    alerts_by_courtid: dict[int | None, set[Alert]] = defaultdict(set)
    debug_match_ids: list[str] = []

    __repr_fields__ = ("rev", "tournament_name", "nmatchstates", "ncourts", "nalerts")
    __str_template__ = "{self.tournament_name}@{self.rev}"
    __eq_fields__ = (
        "rev",
        "tournament",
        "matchstates_by_matchid",
        "court_by_deviceid",
        "alerts_by_courtid",
    )

    @property
    def tournament_name(self) -> str:
        return (
            "(no tournament)" if (t := self.tournament) is None else t.name or "unnamed"
        )

    @property
    def nmatchstates(self) -> int:
        return len(self.matchstates_by_matchid)

    @property
    def ncourts(self) -> int:
        return len(self.court_by_deviceid)

    @property
    def nalerts(self) -> int:
        return len(self.alerts_by_courtid)

    def model_post_init(self, _: Any) -> None:
        self._livedatabuffer: list[LiveData] = []
        self._deviceinfo_by_court: dict[Court, set[DeviceInfo]] = defaultdict(
            set[DeviceInfo]
        )
        self._disable_updates = False
        self._call_after_update_fns: list[UpdateCallable] = []
        self.alerts_by_courtid.setdefault(None, set())

    @field_serializer("alerts_by_courtid", mode="wrap")
    def _alerts_court_key_ser(
        self, value: Any, _: SerializerFunctionWrapHandler
    ) -> dict[int, list[Alert]]:
        def _replace_None_with_minus1(key: int | None) -> int:
            return key if key is not None else -1

        return {_replace_None_with_minus1(k): list(v) for k, v in value.items()}

    @field_validator("alerts_by_courtid", mode="wrap")
    @classmethod
    def _alerts_court_key_val(
        cls, value: Any, handler: ValidatorFunctionWrapHandler
    ) -> Any:
        if isinstance(value, MutableMapping):
            value = {int(k): v for k, v in value.items()}
            alerts_without_court = value.pop(-1, _NONEXISTENT)
            if alerts_without_court is not _NONEXISTENT:
                value[None] = alerts_without_court
        return handler(value)

    def handle_error(self, error: Alert, court: Court | None) -> None:
        logger.error(f"On court {court}: {error}")
        self.alerts_by_courtid[court.id if court is not None else None].add(error)

    def handle_exception(self, exc: Exception, court: Court | None) -> None:
        alert = getattr(exc, "alert", Alert.from_exception(exc))
        self.handle_error(alert, court)

    async def clear_all_errors(self) -> None:
        update = False
        for courtset in self.alerts_by_courtid.values():
            for error in courtset:
                if not error.cleared:
                    error.clear()
                    update = True
        else:
            if update:
                await self._post_update()
        return None

    async def process_deviceinfo(self, devinfo: DeviceInfo) -> None | Never:
        logger.debug(f"Processing device info: {devinfo}")

        # TODO: HERE
        import ipdb

        ipdb.set_trace()  # noqa: E402 E702 I001 # fmt: skip
        # self._devinfobuffer.append(devinfo)
        #
        # for match in tournament.get_matches(
        #     include_played=True, include_not_ready=True
        # ):
        #     if match.id not in self.matchstates_by_matchid:
        #         self.matchstates_by_matchid[match.id] = MatchState(match=match)
        #
        # for buffered in self._livedatabuffer:
        #     await self.process_squore_livedata(buffered)
        # else:
        #     self._livedatabuffer.clear()

        await self._post_update()
        return None

    def set_scoredev_for_court(self, court: Court, devid: str) -> None:
        if self.tournament is not None:
            self.tournament.courts[court.id].scoredev = devid
        return None

    async def process_tournament(self, tournament: TCTournament) -> None | Never:
        logger.debug(f"Processing {tournament.__class__.__name__}: {tournament}")
        self.tournament = tournament

        for devid, court in self.court_by_deviceid.items():
            # TODO: this is a hack until TPTools fills in devids
            if court is None:
                continue
            self.set_scoredev_for_court(court, devid)

        for match in tournament.get_matches(
            include_played=True, include_not_ready=True
        ):
            ipdb.set_trace(cond=match.id in self.debug_match_ids)

            if (ms := self.matchstates_by_matchid.get(match.id)) is None:
                ms = MatchState(match=match)
                self.matchstates_by_matchid[match.id] = ms

            else:
                ms.match = match

            if ms.livedata is None and ms.match.status in (
                MatchStatus.PLAYED,
                MatchStatus.NOTPLAYED,
            ):
                self.matchstates_by_matchid[match.id] = (
                    ms := MatchState.make_from_tcmatch_without_livedata(match)
                )

            if ms.livedata is not None and match.scores:
                if ms.livedata.scores == match.scores:
                    if not ms.acked:
                        logger.info(
                            f"Ack'ing match with ID {match.id} with upstream data"
                        )
                        ms.acked = True

                # We would only need the following if we actually created fake-live
                # TPData from TPMatch, which we don't (see above), as there is no
                # discernable reason to do so.
                #
                # # elif ms.livedata.deviceid == "TournamentSoftware":
                # #     logger.info(f"New result received for match {match.id}")
                # #     self.matchstates_by_matchid[match.id] = (
                # #         self._make_matchstate_from_tpdata(match)
                # #     )

                else:
                    self.handle_error(
                        Alert(
                            text="Upstream match data differ from live state",
                            detail=(
                                f"upstream={match.scores} vs. live={ms.livedata.scores}"
                            ),
                            matchid=match.id,
                        ),
                        court=ms.match.court,
                    )
                    ms.acked = False

        for buffered in self._livedatabuffer:
            await self.process_squore_livedata(buffered)
        else:
            self._livedatabuffer.clear()

        await self._post_update()
        return None

    async def process_squore_livedata(self, data: LiveData) -> None:
        if self.tournament is None:
            logger.warning(
                f"Received livedata for match {data.matchid} "
                "but no tournament is loaded, buffering…"
            )
            self._livedatabuffer.append(data)
            return

        try:
            match = self.tournament.resolve_match_by_id(data.matchid)

        except KeyError:
            if data.court is None:
                court = None
            else:
                try:
                    court = self.tournament.resolve_court_by_id(data.court)

                except KeyError:
                    court = None

            self.handle_error(
                Alert(
                    text="Received livedata for unknown match",
                    matchid=data.matchid,
                    deviceid=data.deviceid,
                ),
                court,
            )
            # ignore error, just continue

        else:
            ipdb.set_trace(cond=match.id in self.debug_match_ids)

            matchstate = self.matchstates_by_matchid.get(
                data.matchid, MatchState(match=match)
            )

            try:
                matchstate.validate_and_receive_livedata(data)

            except TCBoardException as err:
                self.handle_exception(err, match.court)

            # here we have decided that the new state is accepted

            logger.info(f"Received a new MatchState: {matchstate}")
            self.matchstates_by_matchid[data.matchid] = matchstate

            if (
                c := self.court_by_deviceid.get(data.deviceid)
            ) != matchstate.match.court:
                logger.warning(
                    f"Device {data.deviceid} was previously broadcasting about court "
                    f"{c} and is now sending about {matchstate.match.court} "
                    f"({matchstate.match.id})"
                )

            self.court_by_deviceid[data.deviceid] = matchstate.match.court

            if matchstate.match.court is not None and data.devinfo is not None:
                self._deviceinfo_by_court[matchstate.match.court].add(data.devinfo)
                # TODO: hack until TPtools sets device for courts
                self.set_scoredev_for_court(matchstate.match.court, data.deviceid)

            await self._post_update()

    async def ack_match(self, matchid: str, *, acked: bool = True) -> None:
        try:
            if acked:
                self.matchstates_by_matchid[matchid].ack()
            else:
                self.matchstates_by_matchid[matchid].unack()

        except KeyError as exc:
            raise EntityNotFoundError(
                Alert.from_exception(
                    exc,
                    text="Match not found to ack/unack",
                    detail=f"{acked=}",
                    matchid=matchid,
                )
            ) from exc

        else:
            logger.debug(f"Set MatchState.acked to {acked} for match {matchid}")
            await self._post_update()

    async def reset_match(self, matchid: str) -> None:
        try:
            self.matchstates_by_matchid[matchid].reset()

        except KeyError as exc:
            raise EntityNotFoundError(
                Alert.from_exception(
                    exc, text="Match not found to reset", matchid=matchid
                )
            ) from exc

        else:
            logger.debug(f"Reset match {matchid}")
            await self._post_update()

    async def clear_alert(self, courtid: int, alertid: UUID4) -> None:
        for alert in self.alerts_by_courtid[courtid]:
            if alert.cleared:
                continue

            if alert.id == alertid:
                alert.clear()
                logger.debug(f"Cleared error on court with ID {courtid}: {alertid}")
                await self._post_update()
                break

        else:
            raise EntityNotFoundError(
                Alert(
                    text="Alert not found to clear",
                    detail=f"{courtid=}, {alertid=}",
                )
            )

    def get_matchstates_for_court(self, court: Court | None) -> list[MatchState]:
        return [
            ms for ms in self.matchstates_by_matchid.values() if ms.match.court == court
        ]

    def get_matchstates_by_court(self) -> dict[Court | None, MatchState]:
        return {ms.match.court: ms for ms in self.matchstates_by_matchid.values()}

    def get_courtstate_for_court(self, court: Court | None) -> CourtState:
        pending: list[MatchState] = []
        current: list[MatchState] = []
        finished: list[MatchState] = []
        latest_timestamp: datetime | None = None
        for ms in self.get_matchstates_for_court(court):
            msts = cast(datetime, ms.timestamp)
            latest_timestamp = max(latest_timestamp or msts, msts)

            match ms.slot:
                case MatchSlot.PENDING:
                    if not ms.acked:
                        pending.append(ms)
                case MatchSlot.CURRENT:
                    current.append(ms)
                case MatchSlot.FINISHED:
                    finished.append(ms)
                case MatchSlot.HIDDEN:
                    pass
                case _ as slot:
                    self.handle_error(
                        Alert(
                            text=f"MatchState with unknown slot {slot}",
                            detail=str(ms),
                            matchid=ms.match.id,
                            deviceid=ms.livedata.deviceid
                            if ms.livedata is not None
                            else None,
                        ),
                        court,
                    )
                    # ignore matchstate, continue

        if len(current) > 1:
            self.handle_error(
                Alert(
                    text="More than one current match on court",
                    detail=f"{[str(m.livedata) for m in current]}",
                ),
                court,
            )
            # below, we select the latest (first) one, based on timestamp

        batterylevels: dict[str, BatteryStatus | None] = (
            {
                devinfo.deviceid: devinfo.batterystatus
                for devinfo in self._deviceinfo_by_court[court]
                if devinfo.deviceid is not None
            }
            if court is not None
            else {}
        )
        return CourtState(
            court=court,
            pending=sorted(pending),
            current=sorted(
                current,
                key=lambda m: (m.timestamp is not None, m.timestamp),
                reverse=True,
            ),
            finished=sorted(finished, key=lambda x: (x.time is not None, x)),
            tick=latest_timestamp.timestamp() if latest_timestamp is not None else None,
            batterylevels=batterylevels,
            alerts=[
                a
                for a in self.alerts_by_courtid.get(
                    court.id if court is not None else None, []
                )
                if not a.cleared
            ],
        )

    def get_courtstates_by_court(self) -> dict[Court | None, CourtState]:
        courts: Iterable[Court | None]
        if self.tournament is None:
            courts = self.get_matchstates_by_court().keys()
        else:
            courts = self.tournament.get_courts()

        return {c: self.get_courtstate_for_court(c) for c in courts}

    def register_update_function(self, update_fn: UpdateCallable) -> None:
        self._call_after_update_fns.append(update_fn)

    async def _post_update(self, make_dirty: bool = False) -> None:
        if self._disable_updates:
            logger.debug("Not reacting to update, as updates are disabled")
            return

        if make_dirty:
            self.rev += 1

        for fn in self._call_after_update_fns:
            await fn(self)

    @asynccontextmanager
    async def disable_updates(self) -> AsyncGenerator[None]:
        self._disable_updates = True
        logger.debug("Disabling reactions to updates")
        yield
        logger.debug("Re-enabling reactions to updates")
        self._disable_updates = False

    async def update(self, other: TCBoard | None = None, increv: bool = False) -> None:
        if other is not None:
            self.rev = other.rev
            self.tournament = other.tournament
            self.matchstates_by_matchid = other.matchstates_by_matchid
            self.alerts_by_courtid = other.alerts_by_courtid
            self.debug_match_ids = other.debug_match_ids
        await self._post_update(increv)

    def debug_render(
        self, *, npending: int = 3, nfinished: int = 2
    ) -> str:  # pragma: nocover
        cols = ["court", f"rev={self.rev}"]
        for i in range(npending - 1, 0, -1):
            cols.append(f"pend+{i}")
        cols.append("next")
        cols.append("current")
        cols.append("just")
        for i in range(1, nfinished, 1):
            cols.append(f"fin-{i}")

        rows: list[tuple[str, ...]] = [tuple(cols)]
        alerts: list[str] = []

        def make_row(cs: CourtState, npending: int, nfinished: int) -> tuple[str, ...]:
            ret: list[Any] = []
            ret.append(cs.court.name if cs.court is not None else None)
            ret.append(int(cs.tick) if cs.tick is not None else "")

            # pending
            if (lpend := len(cs.pending)) < npending:
                pad = npending - lpend
                pending = cs.pending
            else:
                pad = 0
                pending = cs.pending[0:npending]
            ret.extend([""] * pad + pending[::-1])

            # current
            ret.append(" | ".join([str(m) for m in cs.current]))

            # finished
            finished = cs.finished[::-1][0:nfinished]
            ret.extend(finished + [""] * (nfinished - len(finished)))
            return tuple(str(s) for s in ret)

        def format_alert(court: Court | None, lst: Iterable[Alert]) -> list[str]:
            return [
                (
                    f"  {ts.strftime('%T') if (ts := e.timestamp) else ' ' * 8} "
                    f"{court or 'No court'}: {e.text}"
                )
                for e in lst
                if e.cleared is None
            ]

        try:
            courtstates = self.get_courtstates_by_court()
            for cs in courtstates.values():
                rows.append(make_row(cs, npending, nfinished))
                alerts.extend(
                    format_alert(
                        cs.court,
                        self.alerts_by_courtid[
                            cs.court.id if cs.court is not None else None
                        ],
                    )
                )

            rows.append(
                make_row(self.get_courtstate_for_court(None), npending, nfinished)
            )

        except TournamentNotLoaded:
            return "Tournament not loaded"

        align = ["right", "right"] + ["left"] * (npending + nfinished + 1)
        ret: list[str] = [
            tabulate(
                rows,
                headers="firstrow",
                tablefmt="pretty",
                colalign=align,
            )
        ]

        if alerts:
            ret.append("Alerts:")
            ret.extend(alerts)

        return "\n".join(ret)
