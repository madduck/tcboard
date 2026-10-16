from pytest_mock import MockerFixture
from tptools import Entry, Event, Player
from tptools.namepolicy import (
    ClubNamePolicy,
    CountryNamePolicy,
    DrawNamePolicy,
    PairCombinePolicy,
    PlayerNamePolicy,
)

from tcboard import TCMatch
from tcboard.player import TCPlayerValidator

from .conftest import MatchFactoryType


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
    # Both the full and the short player names come from the same
    # PlayerNamePolicy (patching the class covers the derived short-name
    # policy too), so the calls add up on the single mocked instance.
    assert context["playernamepolicy"].__call__.call_count == 8  # type: ignore[union-attr]
    assert context["paircombinepolicy"].__call__.call_count == 0  # type: ignore[union-attr]
    assert context["drawnamepolicy"].__call__.call_count == 2  # type: ignore[union-attr]


def _named_match(MatchFactory: MatchFactoryType) -> TCMatch:
    event = Event(id=1, name="Event")
    entry_a = Entry(
        id=1,
        event=event,
        player1=Player(id=1, firstname="Alice", lastname="Smith"),
    )
    entry_b = Entry(
        id=2,
        event=event,
        player1=Player(id=2, firstname="Bob", lastname="Jones"),
    )
    return MatchFactory(A=entry_a, B=entry_b)


def test_match_get_players_uses_shortname_policy(
    MatchFactory: MatchFactoryType,
) -> None:
    match = _named_match(MatchFactory)
    playernamepolicy = PlayerNamePolicy(namejoinstr="-")
    playershortnamepolicy = PlayerNamePolicy(fnamemaxlen=1, abbrjoinstr="+")

    players = match.get_players(
        playernamepolicy=playernamepolicy,
        playershortnamepolicy=playershortnamepolicy,
    )

    # full name keeps the full first name and the chosen join string
    assert players[0]["name"] == "Alice-Smith"
    assert players[1]["name"] == "Bob-Jones"
    # the short name abbreviates the first name to a single character
    assert players[0]["shortname"] == "A+Smith"
    assert players[1]["shortname"] == "B+Jones"


def test_match_get_players_defaults_shortname_policy(
    MatchFactory: MatchFactoryType, mocker: MockerFixture
) -> None:
    match = _named_match(MatchFactory)
    playernamepolicy = PlayerNamePolicy(namejoinstr="-")
    original = playernamepolicy.with_
    with_ = mocker.patch.object(PlayerNamePolicy, "with_", wraps=original)

    players = match.get_players(playernamepolicy=playernamepolicy)

    with_.assert_called_once_with(fnamemaxlen=1)
    # the default short policy abbreviates to a single character
    assert players[0]["shortname"] == "A.Smith"


def test_match_serialization_uses_shortname_policy_from_context(
    MatchFactory: MatchFactoryType,
) -> None:
    match = _named_match(MatchFactory)

    dumped = match.model_dump(
        context={
            "playernamepolicy": PlayerNamePolicy(namejoinstr="-"),
            "playershortnamepolicy": PlayerNamePolicy(fnamemaxlen=1, abbrjoinstr="+"),
        }
    )

    assert dumped["players"][0]["name"] == "Alice-Smith"
    assert dumped["players"][0]["shortname"] == "A+Smith"
    assert dumped["players"][1]["name"] == "Bob-Jones"
    assert dumped["players"][1]["shortname"] == "B+Jones"


def test_match_serialization_defaults_shortname_policy_from_playernamepolicy(
    MatchFactory: MatchFactoryType, mocker: MockerFixture
) -> None:
    match = _named_match(MatchFactory)
    playernamepolicy = PlayerNamePolicy(namejoinstr="-")
    original = playernamepolicy.with_
    with_ = mocker.patch.object(PlayerNamePolicy, "with_", wraps=original)

    dumped = match.model_dump(context={"playernamepolicy": playernamepolicy})

    # the field serializer derives a default short-name policy from the
    # full-name policy when none is supplied explicitly
    with_.assert_any_call(fnamemaxlen=1)
    assert dumped["players"][0]["name"] == "Alice-Smith"
    assert dumped["players"][0]["shortname"] == "A.Smith"
