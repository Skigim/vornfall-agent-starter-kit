import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vfkit.wakeon import (Condition, extract_line, fired_by_events, parse_conditions, state_met,
                          time_due)

NOTEBOOK = "== CORE ==\nGOAL: x\n== NOW ==\nWAKE ON: t>=10; mining>=40\nDOUBTS: none\n"


def ev(type_, **data):
    return {"type": type_, "importance": "info", "data": data}


def test_extract_line_from_text_and_json():
    assert extract_line(NOTEBOOK) == "t>=10; mining>=40"
    assert extract_line({"notebook": NOTEBOOK}) == "t>=10; mining>=40"
    assert extract_line({"data": {"a": [1, NOTEBOOK]}}) == "t>=10; mining>=40"
    assert extract_line("no such line") is None
    assert extract_line({"n": 3}) is None


def test_parse_each_kind():
    conds, problems = parse_conditions("t>=280000; mining>=40; coins>=200; hp<=3; bank:tin_ore>=50")
    assert problems == []
    assert conds == [
        Condition("t>=280000", "time", "", 280000),
        Condition("mining>=40", "level", "mining", 40),
        Condition("coins>=200", "coins", "", 200),
        Condition("hp<=3", "hp", "", 3),
        Condition("bank:tin_ore>=50", "bank", "tin_ore", 50),
    ]
    conds, problems = parse_conditions("at=tw_7; event=trade.offered")
    assert conds == [Condition("at=tw_7", "at", "tw_7"),
                     Condition("event=trade.offered", "event", "trade.offered")]


def test_parse_keeps_five_and_reports_the_rest():
    conds, problems = parse_conditions("t>=1; t>=2; t>=3; t>=4; t>=5; t>=6")
    assert [c.text for c in conds] == ["t>=1", "t>=2", "t>=3", "t>=4", "t>=5"]
    assert problems == [("t>=6", "more than 5 conditions")]


def test_parse_drops_nonsense_and_duplicates_and_allows_spaces():
    conds, problems = parse_conditions(" t >= 7 ;; go north; t >= 7 ; woodcutting >= 12 ")
    assert [c.text for c in conds] == ["t >= 7", "woodcutting >= 12"]
    assert conds[0].value == 7 and conds[1].name == "woodcutting"
    assert problems == [("go north", "not a condition this watcher knows")]


def test_parse_empty():
    assert parse_conditions(None) == ([], [])
    assert parse_conditions("") == ([], [])


def test_level_arrival_and_event_match_only_their_events():
    conds, _ = parse_conditions("mining>=40; at=tw_7; event=party.invited")
    events = [ev("skill.level_up", skill="mining", level=39),
              ev("skill.level_up", skill="woodcutting", level=50),
              ev("zone.entered", zone="sanctuary", town="tw_2")]
    assert fired_by_events(conds, events) == []
    events += [ev("skill.level_up", skill="mining", level=40),
               ev("zone.entered", zone="sanctuary", town="tw_7"),
               ev("party.invited", party="pt_1")]
    assert [c.text for c in fired_by_events(conds, events)] == [
        "mining>=40", "at=tw_7", "event=party.invited"]


def test_level_condition_counts_a_higher_level():
    conds, _ = parse_conditions("mining>=40")
    assert fired_by_events(conds, [ev("skill.level_up", skill="mining", level=41)])


def test_time_due():
    cond = parse_conditions("t>=100")[0][0]
    assert not time_due(cond, 99) and time_due(cond, 100) and not time_due(cond, None)


def test_state_met_and_unreadable():
    coins, hp, bank = parse_conditions("coins>=50; hp<=3; bank:tin_ore>=5")[0]
    state = {"coins": 60, "hp": 4, "bank": {"tin_ore": 2}}
    assert state_met(coins, state) is True
    assert state_met(hp, state) is False
    assert state_met(bank, state) is False
    assert state_met(coins, {}) is None and state_met(bank, {}) is None


def test_extract_state_from_the_game_shapes():
    from vfkit.wakeon import extract_state
    me = {"purse": 12, "combat": {"hp": [7, 10], "satiety": 50}}
    bank = {"coins": 30, "items": {"tin_ore": 4, "bread": 2}}
    assert extract_state(me, bank) == {"coins": 42, "hp": 7, "bank": {"tin_ore": 4, "bread": 2}}


def test_extract_state_leaves_out_what_is_missing():
    from vfkit.wakeon import extract_state
    assert extract_state({}, {}) == {}
    assert extract_state({"purse": 5}, {}) == {}
    assert extract_state({"combat": {"hp": []}}, {"items": "x"}) == {}
    assert extract_state(None, None) == {}
