from .alert import Alert


class TCBoardException(Exception):
    def __init__(self, alert: Alert | str) -> None:
        alert = alert if isinstance(alert, Alert) else Alert(text=alert)
        super().__init__(str(alert))
        self._alert = alert

    @property
    def alert(self) -> Alert:
        return self._alert


class TournamentNotLoaded(TCBoardException): ...


class MatchStateConflict(TCBoardException): ...


class MatchFinishedError(TCBoardException): ...


class CourtMismatchError(TCBoardException): ...


class RogueDeviceError(TCBoardException): ...


class EntityNotFoundError(TCBoardException): ...
