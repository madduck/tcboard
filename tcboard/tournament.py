from tptools import Court, Draw, Entry, Tournament

from .match import TCMatch

# type TCTournament = Tournament[Entry, Draw, Court, TCMatch]


class TCTournament(Tournament[Entry, Draw, Court, TCMatch]):
    pass
