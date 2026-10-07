from tcboard.ext.squore import SquoreMatch


def test_matchid_comes_from_metadata(sqmatch: SquoreMatch) -> None:
    assert sqmatch.matchid is sqmatch.metadata.sourceID
