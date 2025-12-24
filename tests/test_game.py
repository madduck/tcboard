from tcboard.game import Game


def test_game_score_list_not_tuple() -> None:
    score = (1, 2)
    assert Game(score=score).model_dump()["score"] == list(score)
