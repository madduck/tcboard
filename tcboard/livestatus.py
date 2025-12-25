# needed < 3.14 so that annotations aren't evaluated
from __future__ import annotations

from enum import IntEnum, auto


class LiveStatus(IntEnum):
    UNKNOWN = 0
    WARMUP = auto()
    PREPARE = auto()
    FIFTEENSECONDS = auto()
    READY = auto()
    ONGOING = auto()
    GAMEBALL = auto()
    BETWEENGAMES = auto()
    MATCHBALL = auto()
    FINISHED = auto()
    EXTERNAL = auto()

    def __str__(self) -> str:
        return self.name

    @property
    def short(self) -> str:
        return {
            self.UNKNOWN: "???",
            self.WARMUP: "WUP",
            self.PREPARE: "PRE",
            self.READY: "RDY",
            self.ONGOING: "ONG",
            self.GAMEBALL: "GBL",
            self.BETWEENGAMES: "PAU",
            self.FIFTEENSECONDS: "15s",
            self.MATCHBALL: "MBL",
            self.FINISHED: "FIN",
            self.EXTERNAL: "EXT",
        }[self]

    def can_come_after(self, other: LiveStatus) -> bool:
        if self == self.UNKNOWN:
            return False

        elif other < self.ONGOING:
            return True

        elif self == self.ONGOING and other in (
            self.BETWEENGAMES,
            self.FIFTEENSECONDS,
            self.GAMEBALL,
            self.MATCHBALL,
        ):
            return True

        elif self == self.FIFTEENSECONDS and other in (self.BETWEENGAMES, self.PREPARE):
            return True

        return self >= other
