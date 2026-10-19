from .board import TCBoard
from .exceptions import TCBoardException
from .match import TCMatch
from .tournament import TCTournament

try:
    from ._version import version as VERSION

except ImportError:  # pragma: nocover
    VERSION = None

__all__ = [
    "TCBoard",
    "TCBoardException",
    "TCMatch",
    "TCTournament",
    "VERSION",
]
