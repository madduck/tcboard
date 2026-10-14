"""The tcboard-side Squore match.

The data structure itself lives in :mod:`squoredata`; this module adds the
tcboard-specific constructor helpers and re-exports the nested models so that
existing imports keep working.
"""

from typing import Any, Self

from squoredata import Clubs, Colors, Countries, Event, Format, Metadata, Players, Wifi
from squoredata import SquoreMatch as SquoreMatchBase
from tptools import Entry, Match
from tptools.entry import PlayerExportStruct
from tptools.namepolicy import CountryNamePolicy

__all__ = [
    "Clubs",
    "Colors",
    "Countries",
    "Event",
    "Format",
    "Metadata",
    "Players",
    "SquoreMatch",
    "Wifi",
]


class SquoreMatch(SquoreMatchBase):
    """A Squore match, constructible from a tptools match."""

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
