import logging

from pydantic import (
    UUID4,
    BaseModel,
    SerializationInfo,
    computed_field,
    field_serializer,
)
from tptools import Court
from tptools.mixins import ComparableMixin, ReprMixin, StrMixin
from tptools.namepolicy import CourtNamePolicy

from tcboard.livedata import LiveData

from .alert import Alert
from .devinfo import BatteryStatus
from .matchstate import MatchState

logger = logging.getLogger(__name__)


class CourtState[MatchStateT: MatchState[LiveData]](
    ComparableMixin,
    ReprMixin,
    StrMixin,
    BaseModel,
    json_schema_serialization_defaults_required=True,
):
    court: Court | None
    pending: list[MatchStateT] = []
    current: list[MatchStateT] = []
    finished: list[MatchStateT] = []
    tick: float | None = None
    batterylevels: dict[str, BatteryStatus] = {}
    alerts: list[Alert] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def courtid(self) -> int | None:
        return self.court.id if self.court is not None else None

    @field_serializer("court", mode="plain")
    def _court_serializer(self, value: Court, info: SerializationInfo) -> str:
        ctx = info.context or {}
        return (ctx.get("courtnamepolicy") or CourtNamePolicy())(value)

    @field_serializer("current", mode="plain")
    def _sort_by_desc_timestamp(self, current: list[MatchStateT]) -> list[MatchStateT]:
        return sorted(
            current,
            key=lambda m: (m.timestamp is not None, m.timestamp),
            reverse=True,
        )

    @property
    def _alert_uuids(self) -> list[UUID4]:
        return [a.id for a in self.alerts if not a.cleared]

    __cmp_fields__ = ("court", "tick")
    __eq_fields__ = (
        "court",
        "pending",
        "current",
        "finished",
        "tick",
        "batterylevels",
        "_alert_uuids",
    )
    __repr_fields__ = [
        "court?.name",
        ("pending", lambda s: [str(m) for m in s.pending], False),
        ("current", lambda s: [str(c) for c in s.current] or None, False),
        ("finished", lambda s: [str(m) for m in s.finished], False),
        ("nalerts", lambda s: len([s for s in s.alerts if not s.cleared]), False),
    ]
    __str_template__ = "{self.court}"
