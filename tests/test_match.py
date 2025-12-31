from pytest_mock import MockerFixture
from tptools.namepolicy import (
    ClubNamePolicy,
    CountryNamePolicy,
    DrawNamePolicy,
    PairCombinePolicy,
    PlayerNamePolicy,
)

from tcboard import TCMatch
from tcboard.player import TCPlayerValidator


def test_match_players_are_tcplayers(match: TCMatch) -> None:
    for player in match.players:
        assert TCPlayerValidator.validate_python(player)


def test_match_placeholder(match: TCMatch) -> None:
    name = "AbcDef"
    match = match.model_copy(update={"A": name})
    assert name in match.players[0]["name"]
    assert name == match.players[0]["shortname"]


def test_match_serialization_invokes_policies(
    match: TCMatch, mocker: MockerFixture
) -> None:
    context = {}
    for pol in (
        ClubNamePolicy,
        CountryNamePolicy,
        PlayerNamePolicy,
        PairCombinePolicy,
        DrawNamePolicy,
    ):
        name = pol.__name__.lower()
        mocker.patch.object(pol, "__call__", return_value=name)
        context[name] = pol()

    _ = match.model_dump(context=context)

    assert context["clubnamepolicy"].__call__.call_count == 4  # type: ignore[union-attr]
    assert context["countrynamepolicy"].__call__.call_count == 4  # type: ignore[union-attr]
    assert context["playernamepolicy"].__call__.call_count == 8  # type: ignore[union-attr]
    assert context["paircombinepolicy"].__call__.call_count == 0  # type: ignore[union-attr]
    assert context["drawnamepolicy"].__call__.call_count == 2  # type: ignore[union-attr]
