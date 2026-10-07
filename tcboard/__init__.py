from .exceptions import TCBoardException
from .match import TCMatch
from .tournament import TCTournament

VERSION: str | None
try:
    from ._version import version as VERSION

except ImportError:  # pragma: nocover
    Version = None

__all__ = [
    "TCBoardException",
    "TCMatch",
    "TCTournament",
    "VERSION",
]
