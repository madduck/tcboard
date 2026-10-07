from typing import Any, Literal, Self

from pydantic import BaseModel
from tptools import Entry, Match
from tptools.entry import PlayerExportStruct
from tptools.namepolicy import CountryNamePolicy

from .devinfo import SquoreDeviceInfo


class Players(BaseModel, extra="forbid"):
    A: str
    B: str


class PlayersProps(BaseModel, extra="forbid"):
    A: str | None = None
    B: str | None = None


class Colors(PlayersProps): ...


class Countries(PlayersProps): ...


class Clubs(PlayersProps): ...


class Event(BaseModel, extra="forbid"):
    name: str
    division: str


class Format(BaseModel, extra="forbid"):
    numberOfPointsToWinGame: int = 11
    numberOfGamesToWinMatch: int = 3
    useHandInHandOutScoring: bool = False


class Wifi(BaseModel, extra="forbid"):
    ipaddress: str | None = None
    ssid: str | None = None


class Metadata(BaseModel, extra="forbid"):
    sourceID: str
    device: SquoreDeviceInfo | None = None
    source: str | None = None
    version: int | None = None
    language: str | None = None
    wifi: Wifi | None = None
    shareURL: str | None = None
    sourceFeedbackState: (
        Literal["SourceAcceptedFinalResult"] | Literal["SourceRejectedResult"] | None
    ) = None
    sourcePostResultUrl: str | None = None


class SquoreMatch(BaseModel, extra="forbid"):
    players: Players
    clubs: Clubs | None = None
    colors: Colors | None = None
    countries: Countries | None = None
    event: Event
    format: Format
    metadata: Metadata

    @property
    def matchid(self) -> str:
        return self.metadata.sourceID

    @staticmethod
    def _get_constructor_data(match: Match) -> dict[str, Any]:
        a = (
            match.A.make_player_export_struct(
                countrynamepolicy=CountryNamePolicy(use_country_code=True)
            )
            if isinstance(match.A, Entry)
            else PlayerExportStruct(name=match.A)
        )
        b = (
            match.B.make_player_export_struct(
                countrynamepolicy=CountryNamePolicy(use_country_code=True)
            )
            if isinstance(match.B, Entry)
            else PlayerExportStruct(name=match.B)
        )

        return {
            "players": Players(A=a["name"], B=b["name"]),
            "countries": Countries(A=a.get("country"), B=b.get("country")),
            "clubs": Clubs(A=a.get("club"), B=b.get("club")),
            "event": Event(name=str(match.draw), division=str(match.court)),
            "format": Format(),
            "metadata": Metadata(sourceID=match.id),
        }

    @classmethod
    def from_match(cls, match: Match) -> Self:
        return cls(**cls._get_constructor_data(match))
