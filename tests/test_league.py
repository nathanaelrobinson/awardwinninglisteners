import random
import pytest
from winspool import league
from winspool.league import LeagueError
from winspool.draft import PICK_ORDER

PLAYERS = ["Nate Robinson", "Evan Goguillon-Bader", "Logan Borgelt",
           "Eric Whitley", "Mitch Fischer"]


PIN = "awardwinninglisteners"


def fresh():
    return league.new_league(PLAYERS, "Nate Robinson", {p: PIN for p in PLAYERS})


def drafting():
    return league.randomize(fresh(), random.Random(1))


def name_for_slot(doc, slot):
    return next(n for n, s in doc["slots"].items() if s == slot)


def test_new_league_shape():
    d = fresh()
    assert d["status"] == "lobby"
    assert d["players"] == PLAYERS
    assert d["slots"] is None
    assert d["picks"] == []
    assert d["overrides"] == {}
    assert PIN not in str(d)  # only the hash is stored


def test_new_league_missing_pin_raises_400():
    with pytest.raises(LeagueError) as e:
        league.new_league(PLAYERS, "Nate Robinson",
                          {p: PIN for p in PLAYERS[:-1]})
    assert e.value.status == 400


def test_check_pin():
    d = fresh()
    assert league.check_pin(d, "Nate Robinson", PIN)
    assert not league.check_pin(d, "Nate Robinson", "wrong")
    assert not league.check_pin(d, "Nobody", PIN)


def test_check_pin_is_per_player():
    d = league.new_league(PLAYERS, "Nate Robinson",
                          {"Nate Robinson": "1111", "Evan Goguillon-Bader": "2222",
                           "Logan Borgelt": "3333", "Eric Whitley": "4444",
                           "Mitch Fischer": "5555"})
    assert league.check_pin(d, "Nate Robinson", "1111")
    assert not league.check_pin(d, "Nate Robinson", "2222")
    assert not league.check_pin(d, "Evan Goguillon-Bader", "1111")


def test_randomize_assigns_permutation_and_starts_draft():
    d = drafting()
    assert d["status"] == "drafting"
    assert sorted(d["slots"].values()) == [1, 2, 3, 4, 5]
    assert set(d["slots"]) == set(PLAYERS)


def test_randomize_only_in_lobby():
    with pytest.raises(LeagueError) as e:
        league.randomize(drafting(), random.Random(1))
    assert e.value.status == 409


def test_reset_returns_to_lobby_only_before_picks():
    d = league.reset(drafting())
    assert d["status"] == "lobby" and d["slots"] is None
    d = drafting()
    d = league.pick(d, name_for_slot(d, PICK_ORDER[0]), "KC", 1.0)
    with pytest.raises(LeagueError):
        league.reset(d)


def test_pick_by_current_player_appends():
    d = drafting()
    who = name_for_slot(d, PICK_ORDER[0])
    d = league.pick(d, who, "KC", 1.0)
    assert d["picks"] == [{"n": 1, "slot": PICK_ORDER[0], "team": "KC", "by": who, "ts": 1.0}]
    assert league.current_slot(d) == PICK_ORDER[1]


def test_pick_out_of_turn_409():
    d = drafting()
    wrong = name_for_slot(d, PICK_ORDER[1])
    with pytest.raises(LeagueError) as e:
        league.pick(d, wrong, "KC", 1.0)
    assert e.value.status == 409


def test_pick_taken_team_409():
    d = drafting()
    d = league.pick(d, name_for_slot(d, PICK_ORDER[0]), "KC", 1.0)
    with pytest.raises(LeagueError) as e:
        league.pick(d, name_for_slot(d, PICK_ORDER[1]), "kc", 2.0)
    assert e.value.status == 409


def test_pick_unknown_team_400():
    d = drafting()
    with pytest.raises(LeagueError) as e:
        league.pick(d, name_for_slot(d, PICK_ORDER[0]), "XXX", 1.0)
    assert e.value.status == 400


def test_pick_in_lobby_409():
    with pytest.raises(LeagueError):
        league.pick(fresh(), PLAYERS[0], "KC", 1.0)


def test_thirty_picks_finishes_and_undo_reopens():
    from winspool.teams import TEAMS
    d = drafting()
    for i in range(30):
        d = league.pick(d, name_for_slot(d, PICK_ORDER[i]), TEAMS[i], float(i))
    assert d["status"] == "done"
    assert league.current_slot(d) is None
    with pytest.raises(LeagueError):
        league.pick(d, PLAYERS[0], TEAMS[30], 99.0)
    d = league.undo(d)
    assert d["status"] == "drafting" and len(d["picks"]) == 29


def test_undo_with_no_picks_409():
    with pytest.raises(LeagueError):
        league.undo(drafting())


def test_view_has_rosters_by_name_and_no_hash():
    d = drafting()
    who = name_for_slot(d, PICK_ORDER[0])
    d = league.pick(d, who, "KC", 1.0)
    v = league.view(d)
    assert v["rosters"][who] == ["KC"]
    assert v["current_slot"] == PICK_ORDER[1]
    assert v["current_player"] == name_for_slot(d, PICK_ORDER[1])
    assert v["pick_order"] == PICK_ORDER
    assert "pins" not in v


def test_view_and_doc_never_expose_raw_pins():
    d = league.new_league(PLAYERS, "Nate Robinson",
                          {"Nate Robinson": "1111", "Evan Goguillon-Bader": "2222",
                           "Logan Borgelt": "3333", "Eric Whitley": "4444",
                           "Mitch Fischer": "5555"})
    v = league.view(d)
    assert "pins" not in v
    for raw in ("1111", "2222", "3333", "4444", "5555"):
        assert raw not in str(d)
        assert raw not in str(v)


def test_inmemory_store_update_is_atomic_and_returns_new_doc():
    from winspool.store import InMemoryStore
    s = InMemoryStore(fresh())
    out = s.update(lambda d: league.randomize(d, random.Random(3)))
    assert out["status"] == "drafting"
    assert s.get()["status"] == "drafting"


def test_inmemory_store_messages():
    from winspool.store import InMemoryStore
    s = InMemoryStore(fresh())
    m1 = s.add_message("Mitch Fischer", "lol")
    m2 = s.add_message("Nate Robinson", "ok")
    assert [m["text"] for m in s.messages(None)] == ["lol", "ok"]
    assert [m["text"] for m in s.messages(m1["ts"])] == ["ok"]
    assert m2["by"] == "Nate Robinson" and "id" in m2
