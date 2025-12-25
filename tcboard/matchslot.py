from enum import StrEnum, auto


class MatchSlot(StrEnum):
    UNKNOWN = auto()
    PENDING = auto()
    CURRENT = auto()
    FINISHED = auto()
    HIDDEN = auto()

    def __str__(self) -> str:
        return self.value.upper()
