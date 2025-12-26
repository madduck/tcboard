from typing import NotRequired

from pydantic import TypeAdapter
from tptools.entry import PlayerExportStruct


class TCPlayer(PlayerExportStruct):
    shortname: str
    colour: NotRequired[str]


# type PlayersTuple = tuple[TCPlayer, TCPlayer]
# TODO: using a tuple here means that json2ts generates:
#
# /**
#  * @minItems 2
#  * @maxItems 2
#  */
# export type PlayersTuple = [unknown, unknown];
#
# and thus loses the typing. So for now, use a list:
type PlayersTuple = list[TCPlayer]

TCPlayerValidator = TypeAdapter(TCPlayer)
