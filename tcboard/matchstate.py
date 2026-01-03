# needed < 3.14 so that annotations aren't evaluated
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Never, cast

from pydantic import (
    BaseModel,
    computed_field,
)
from tptools import Court, Draw, Entry, Tournament
from tptools.mixins import ComparableMixin, ReprMixin

from .alert import Alert
from .exceptions import (
    CourtMismatchError,
    MatchStateConflict,
    RogueDeviceError,
)
from .livedata import LiveData
from .livestatus import LiveStatus
from .match import TCMatch
from .matchslot import MatchSlot

logger = logging.getLogger(__name__)


type TCTournament = Tournament[Entry, Draw, Court, TCMatch]


class MatchState[LiveDataT: LiveData](
    ComparableMixin,
    ReprMixin,
    BaseModel,
    json_schema_serialization_defaults_required=True,
):
    match: TCMatch
    livedata: LiveDataT | None = None
    timestamp: datetime | None = None
    locked: bool = False
    acked: bool = False

    def model_post_init(self, _: Any) -> None:
        if self.timestamp is None:
            self.timestamp = (
                self.livedata.timestamp if self.livedata is not None else datetime.now()
            )

    # @model_serializer(mode="wrap")
    # def _model_serializer(  # type: ignore[no-untyped-def]
    #     self, handler: SerializerFunctionWrapHandler
    # ):  # No return type to avoid losing refs/defs in JSON schema
    #     ret = handler(self)
    #     ret["_livedata.modelid"] = (
    #         self.livedata.modelid if self.livedata is not None else None
    #     )
    #     return ret

    # @model_validator(mode="wrap")
    # @classmethod
    # def _model_validator(
    #     cls,
    #     data: dict[str, Any] | Self,
    #     handler: ValidatorFunctionWrapHandler,
    # ) -> Self:
    #     livedata = None
    #     if isinstance(data, MutableMapping):
    #         modelid = data.pop("_livedata.modelid", None)
    #
    #         if modelid is not None:
    #             livedata = cast(
    #                 LiveDataT,
    #                 LiveData.make_model_instance(data.pop("livedata"),
    #                 modelid=modelid),
    #             )
    #
    #     ret: Self = handler(data)
    #
    #     if livedata is not None:
    #         ret.livedata = livedata
    #
    #     return ret

    # @field_serializer("match", mode="plain")
    # def _match_to_tcmatch(self, match: Match, info: SerializationInfo) -> TCMatch:
    #     return TCMatch.from_match(match)

    def ack(self) -> None:
        self.acked = True

    def unack(self) -> None:
        self.acked = False

    def reset(self) -> None:
        self.livedata = None

    def lock(self) -> None:
        self.locked = True

    def unlock(self) -> None:
        self.locked = False

    @property
    def slot(self) -> MatchSlot:
        if self.livedata is None:
            return MatchSlot.PENDING

        elif (status := self.livedata.status) == LiveStatus.FINISHED:
            return MatchSlot.FINISHED

        elif status == LiveStatus.EXTERNAL:
            return MatchSlot.HIDDEN

        elif status >= LiveStatus.WARMUP:
            return MatchSlot.CURRENT

        return MatchSlot.UNKNOWN

    def validate_and_receive_livedata(self, data: LiveDataT) -> None | Never:
        data.validate_livedata()

        if self.livedata is None:
            self.livedata = data
            self.timestamp = data.timestamp
            return None

        elif self.livedata.court != data.court:
            raise CourtMismatchError(
                Alert(
                    text="Match is on one court, livedata has another",
                    detail=(
                        f"Match: {self.match.court} vs livedata court ID: {data.court}"
                    ),
                    matchid=self.match.id,
                    deviceid=data.deviceid,
                )
            )

        if self.livedata.deviceid != data.deviceid:
            raise RogueDeviceError(
                Alert(
                    text=(
                        "Received livedata from a different device "
                        "than previously for match"
                    ),
                    detail=f"Previously: {self.livedata.deviceid}",
                    matchid=self.match.id,
                    deviceid=data.deviceid,
                )
            )

        if not data.can_come_after(self.livedata):
            raise MatchStateConflict(
                Alert(
                    text=(
                        "Livedata out of line with existing data "
                        f"@ {self.livedata.status}"
                    ),
                    detail=repr(data),
                    matchid=self.match.id,
                    deviceid=data.deviceid,
                )
            )
            # TODO: asses what we should do here. We do not want e.g. a new match to
            # replace an ongoing match, but this check also cannot be too tight, as
            # there *will* be stray packets.
            #
            # One consideration: keep a counter, and ignore until a repeated number of
            # times this has happened…

        logger.debug(
            f"New data with status {data.status} for match {self.livedata.matchid} "
            f"from device {data.deviceid} "
            f"replaces livedata at status {self.livedata.status}: {data!r}"
        )
        self.livedata = data
        self.timestamp = data.timestamp

        return None

    @property
    def time(self) -> datetime | None:
        match self.slot:
            case MatchSlot.PENDING:
                return self.match.time
            case MatchSlot.CURRENT:
                assert self.livedata is not None
                return self.livedata.starttime
            case MatchSlot.FINISHED:
                return cast(LiveDataT, self.livedata).endtime
            case _:
                return None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status(self) -> str | None:
        if self.livedata is not None:
            return self.livedata.status.name.lower()

        return None

    def debug_repr(self) -> str:
        return self._as_str(debug=True)

    def __str__(self) -> str:
        return self._as_str()

    def _as_str(self, *, debug: bool = False) -> str:
        _ = debug  # TODO: unused for now
        m, ld = self.match, self.livedata
        ret = []

        if time := self.time:
            ret.append(time.strftime("%H:%M"))
        else:
            ret.append("??:??")

        ret.append(m.id)

        if self.locked:
            ret.append("🔒")

        if self.acked:
            ret.append("✓")

        elif ld:
            ret.append("-".join([str(x) for x in ld.matchscore]))

        return " ".join(ret)

    __cmp_fields__ = ("time",)
    __eq_fields__ = ("match", "livedata", "locked", "acked")
    __repr_fields__ = ("match", "livedata", "locked", "acked")
