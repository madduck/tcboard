from tptools import Court, Draw, Entry, Tournament

from .match import TCMatch

type TCTournament = Tournament[Entry, Draw, Court, TCMatch]
