import logging

from pydantic import (
    SerializationInfo,
    computed_field,
    field_serializer,
)
from tptools import Draw, Entry, Match
from tptools.namepolicy import (
    ClubNamePolicy,
    CountryNamePolicy,
    DrawNamePolicy,
    PairCombinePolicy,
    PlayerNamePolicy,
)

from .player import PlayersTuple, TCPlayer

logger = logging.getLogger(__name__)


class TCMatch(Match):
    def get_players(
        self,
        clubnamepolicy: ClubNamePolicy | None = None,
        countrynamepolicy: CountryNamePolicy | None = None,
        playernamepolicy: PlayerNamePolicy | None = None,
        paircombinepolicy: PairCombinePolicy | None = None,
    ) -> PlayersTuple:
        clubnamepolicy = clubnamepolicy or ClubNamePolicy()
        countrynamepolicy = countrynamepolicy or CountryNamePolicy()
        playernamepolicy = playernamepolicy or PlayerNamePolicy()
        paircombinepolicy = paircombinepolicy or PairCombinePolicy()

        def make_tcplayer(entry: Entry | str) -> TCPlayer:
            if isinstance(entry, str):
                return TCPlayer(
                    name=f"*{entry}*", shortname=entry.replace(" of match", "")
                )

            expplayer = entry.make_player_export_struct(
                clubnamepolicy=clubnamepolicy,
                countrynamepolicy=countrynamepolicy,
                playernamepolicy=playernamepolicy,
                paircombinepolicy=paircombinepolicy,
            )
            return TCPlayer(
                shortname=entry.get_player_name(
                    playernamepolicy=playernamepolicy.with_(fnamemaxlen=1),
                    paircombinepolicy=paircombinepolicy,
                ),
                **expplayer,  # type: ignore[typeddict-item]
            )

        return [make_tcplayer(p) for p in (self.A, self.B)]

    players = computed_field(property(get_players))

    @field_serializer("players", mode="plain")
    def _players_with_context(
        self, _: PlayersTuple, info: SerializationInfo
    ) -> PlayersTuple:
        ctx = info.context or {}
        clubnamepolicy: ClubNamePolicy = ctx.get("clubnamepolicy", ClubNamePolicy())
        countrynamepolicy: CountryNamePolicy = ctx.get(
            "countrynamepolicy", CountryNamePolicy()
        )
        playernamepolicy: PlayerNamePolicy = ctx.get(
            "playernamepolicy", PlayerNamePolicy()
        )
        paircombinepolicy: PairCombinePolicy = ctx.get(
            "paircombinepolicy", PairCombinePolicy()
        )
        return self.get_players(
            clubnamepolicy=clubnamepolicy,
            countrynamepolicy=countrynamepolicy,
            playernamepolicy=playernamepolicy,
            paircombinepolicy=paircombinepolicy,
        )

    def get_drawname(self, drawnamepolicy: DrawNamePolicy | None = None) -> str:
        drawnamepolicy = drawnamepolicy or DrawNamePolicy()
        return drawnamepolicy(self.draw)

    drawname = computed_field(property(get_drawname))

    @field_serializer("drawname", mode="plain")
    def _apply_drawnamepolicy(self, _: Draw, info: SerializationInfo) -> str:
        ctx = info.context or {}
        drawnamepolicy: DrawNamePolicy = ctx.get("drawnamepolicy", DrawNamePolicy())
        return self.get_drawname(drawnamepolicy=drawnamepolicy)
